from datetime import date
from decimal import Decimal

import pytest_asyncio
from app.models.claim import Claim
from app.models.outbox import OutboxEvent
from app.models.policy import Policy
from app.models.user import User
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

FNOL = {
    "policy_number": "MOT-2026-0001",
    "loss_date": "2026-05-14",
    "loss_type": "collision",
    "description": "Rear-ended at a signal on Hosur Road, bumper and boot damage.",
    "claimed_amount": "120000.00",
}


@pytest_asyncio.fixture
async def policy(session: AsyncSession) -> Policy:
    record = Policy(
        policy_number="MOT-2026-0001",
        policyholder_name="Ananya Rao",
        product_type="motor",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        coverage_limit=Decimal("800000.00"),
        deductible=Decimal("5000.00"),
    )
    session.add(record)
    await session.commit()
    return record


async def _events(session: AsyncSession) -> list[OutboxEvent]:
    result = await session.execute(select(OutboxEvent).order_by(OutboxEvent.created_at))
    return list(result.scalars())


async def test_submission_writes_one_outbox_event(
    client: AsyncClient, session: AsyncSession, policy: Policy, adjuster: User, auth_header
):
    response = await client.post("/claims", headers=auth_header(adjuster), json=FNOL)
    claim_id = response.json()["id"]

    events = await _events(session)

    assert len(events) == 1
    assert events[0].event_type == "claim.submitted"
    assert events[0].aggregate_type == "claim"
    assert str(events[0].aggregate_id) == claim_id
    assert events[0].published_at is None


async def test_transition_writes_status_changed_event(
    client: AsyncClient, session: AsyncSession, policy: Policy, adjuster: User, auth_header
):
    headers = auth_header(adjuster)
    claim_id = (await client.post("/claims", headers=headers, json=FNOL)).json()["id"]
    await client.post(
        f"/claims/{claim_id}/transitions",
        headers=headers,
        json={"to_status": "under_review"},
    )

    events = await _events(session)

    assert [event.event_type for event in events] == [
        "claim.submitted",
        "claim.status_changed",
    ]
    business = events[1].envelope["payload"]
    assert business["from_status"] == "submitted"
    assert business["to_status"] == "under_review"
    assert business["actor_id"] == str(adjuster.id)


async def test_rejected_transition_writes_no_event(
    client: AsyncClient, session: AsyncSession, policy: Policy, adjuster: User, auth_header
):
    """The core atomicity guarantee: no event without the state change."""
    headers = auth_header(adjuster)
    claim_id = (await client.post("/claims", headers=headers, json=FNOL)).json()["id"]
    await client.post(
        f"/claims/{claim_id}/transitions", headers=headers, json={"to_status": "under_review"}
    )

    rejected = await client.post(
        f"/claims/{claim_id}/transitions",
        headers=headers,
        json={"to_status": "approved", "settlement_amount": "999999.00"},
    )
    assert rejected.status_code == 403

    events = await _events(session)
    assert [event.event_type for event in events] == [
        "claim.submitted",
        "claim.status_changed",
    ]


async def test_failed_submission_writes_no_event(
    client: AsyncClient, session: AsyncSession, adjuster: User, auth_header
):
    response = await client.post(
        "/claims", headers=auth_header(adjuster), json={**FNOL, "policy_number": "NOPE-1"}
    )
    assert response.status_code == 422

    assert await _events(session) == []
    assert await session.scalar(select(func.count()).select_from(Claim)) == 0


async def test_event_ids_are_unique_across_claims(
    client: AsyncClient, session: AsyncSession, policy: Policy, adjuster: User, auth_header
):
    headers = auth_header(adjuster)
    for _ in range(3):
        await client.post("/claims", headers=headers, json=FNOL)

    events = await _events(session)
    assert len({event.event_id for event in events}) == 3


async def test_payload_round_trips_through_the_envelope(
    client: AsyncClient, session: AsyncSession, policy: Policy, adjuster: User, auth_header
):
    from claims_events import EventEnvelope

    await client.post("/claims", headers=auth_header(adjuster), json=FNOL)
    event = (await _events(session))[0]

    envelope = EventEnvelope.model_validate(event.envelope)

    assert envelope.event_id == event.event_id
    assert envelope.partition_key == str(event.aggregate_id).encode("utf-8")
