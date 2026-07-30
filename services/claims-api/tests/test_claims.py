from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from app.models.policy import Policy
from app.models.user import User
from httpx import AsyncClient
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


async def submit(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.post("/claims", headers=headers, json=FNOL)
    assert response.status_code == 201
    return response.json()


async def move(
    client: AsyncClient,
    headers: dict[str, str],
    claim_id: str,
    to_status: str,
    **extra,
):
    return await client.post(
        f"/claims/{claim_id}/transitions",
        headers=headers,
        json={"to_status": to_status, **extra},
    )


async def test_submit_claim_starts_in_submitted(
    client: AsyncClient, policy: Policy, adjuster: User, auth_header
):
    claim = await submit(client, auth_header(adjuster))

    assert claim["status"] == "submitted"
    assert claim["claim_number"].startswith("CLM-")
    assert claim["assigned_adjuster_id"] is None


async def test_submit_requires_authentication(client: AsyncClient, policy: Policy):
    assert (await client.post("/claims", json=FNOL)).status_code == 401


async def test_unknown_policy_is_rejected(client: AsyncClient, adjuster: User, auth_header):
    response = await client.post(
        "/claims", headers=auth_header(adjuster), json={**FNOL, "policy_number": "NOPE-1"}
    )
    assert response.status_code == 422


async def test_loss_date_outside_policy_period_is_rejected(
    client: AsyncClient, policy: Policy, adjuster: User, auth_header
):
    response = await client.post(
        "/claims", headers=auth_header(adjuster), json={**FNOL, "loss_date": "2025-05-14"}
    )
    assert response.status_code == 422


async def test_submission_writes_history(
    client: AsyncClient, policy: Policy, adjuster: User, auth_header
):
    claim = await submit(client, auth_header(adjuster))
    response = await client.get(f"/claims/{claim['id']}/history", headers=auth_header(adjuster))

    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["from_status"] is None
    assert entries[0]["to_status"] == "submitted"
    assert entries[0]["actor_type"] == "system"


async def test_taking_a_claim_assigns_the_adjuster(
    client: AsyncClient, policy: Policy, adjuster: User, auth_header
):
    claim = await submit(client, auth_header(adjuster))
    response = await move(client, auth_header(adjuster), claim["id"], "under_review")

    assert response.status_code == 200
    assert response.json()["assigned_adjuster_id"] == str(adjuster.id)


async def test_illegal_transition_returns_409(
    client: AsyncClient, policy: Policy, adjuster: User, auth_header
):
    claim = await submit(client, auth_header(adjuster))
    response = await move(
        client, auth_header(adjuster), claim["id"], "settled", settlement_amount="1000.00"
    )

    assert response.status_code == 409


async def test_approval_above_authority_returns_403(
    client: AsyncClient, policy: Policy, adjuster: User, auth_header
):
    headers = auth_header(adjuster)
    claim = await submit(client, headers)
    await move(client, headers, claim["id"], "under_review")

    response = await move(client, headers, claim["id"], "approved", settlement_amount="60000.00")

    assert response.status_code == 403
    assert "authority limit" in response.json()["detail"]


async def test_approval_without_amount_returns_422(
    client: AsyncClient, policy: Policy, adjuster: User, auth_header
):
    headers = auth_header(adjuster)
    claim = await submit(client, headers)
    await move(client, headers, claim["id"], "under_review")

    assert (await move(client, headers, claim["id"], "approved")).status_code == 422


async def test_adjuster_approves_within_authority(
    client: AsyncClient, policy: Policy, adjuster: User, auth_header
):
    headers = auth_header(adjuster)
    claim = await submit(client, headers)
    await move(client, headers, claim["id"], "under_review")

    response = await move(client, headers, claim["id"], "approved", settlement_amount="40000.00")

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["settled_amount"] == "40000.00"


async def test_four_eyes_blocks_self_approval(
    client: AsyncClient, policy: Policy, senior: User, auth_header
):
    headers = auth_header(senior)
    claim = await submit(client, headers)
    await move(client, headers, claim["id"], "under_review")
    await move(client, headers, claim["id"], "pending_approval", settlement_amount="90000.00")

    response = await move(client, headers, claim["id"], "approved", settlement_amount="90000.00")

    assert response.status_code == 403
    assert "other than" in response.json()["detail"]


async def test_senior_approves_claim_escalated_by_adjuster(
    client: AsyncClient, policy: Policy, adjuster: User, senior: User, auth_header
):
    adjuster_headers = auth_header(adjuster)
    claim = await submit(client, adjuster_headers)
    await move(client, adjuster_headers, claim["id"], "under_review")
    await move(
        client,
        adjuster_headers,
        claim["id"],
        "pending_approval",
        settlement_amount="90000.00",
    )

    response = await move(
        client, auth_header(senior), claim["id"], "approved", settlement_amount="90000.00"
    )

    assert response.status_code == 200


async def test_full_lifecycle_history_is_ordered(
    client: AsyncClient, policy: Policy, adjuster: User, auth_header
):
    headers = auth_header(adjuster)
    claim = await submit(client, headers)
    await move(client, headers, claim["id"], "under_review")
    await move(client, headers, claim["id"], "approved", settlement_amount="30000.00")
    await move(client, headers, claim["id"], "settled")

    entries = (await client.get(f"/claims/{claim['id']}/history", headers=headers)).json()

    assert [entry["to_status"] for entry in entries] == [
        "submitted",
        "under_review",
        "approved",
        "settled",
    ]


async def test_available_transitions_reflect_role(
    client: AsyncClient, policy: Policy, adjuster: User, senior: User, auth_header
):
    headers = auth_header(adjuster)
    claim = await submit(client, headers)
    await move(client, headers, claim["id"], "under_review")
    await move(client, headers, claim["id"], "approved", settlement_amount="30000.00")
    await move(client, headers, claim["id"], "settled")

    as_adjuster = (await client.get(f"/claims/{claim['id']}", headers=headers)).json()[
        "available_transitions"
    ]
    as_senior = (await client.get(f"/claims/{claim['id']}", headers=auth_header(senior))).json()[
        "available_transitions"
    ]

    assert as_adjuster == []
    assert as_senior == ["under_review"]


async def test_missing_claim_returns_404(client: AsyncClient, adjuster: User, auth_header):
    missing = "00000000-0000-0000-0000-000000000000"
    response = await client.get(f"/claims/{missing}", headers=auth_header(adjuster))
    assert response.status_code == 404


async def test_list_filters_by_status(
    client: AsyncClient, policy: Policy, adjuster: User, auth_header
):
    headers = auth_header(adjuster)
    first = await submit(client, headers)
    await submit(client, headers)
    await move(client, headers, first["id"], "under_review")

    submitted = (await client.get("/claims?status=submitted", headers=headers)).json()
    under_review = (await client.get("/claims?status=under_review", headers=headers)).json()

    assert submitted["total"] == 1
    assert under_review["total"] == 1


async def test_list_mine_filter(
    client: AsyncClient, policy: Policy, adjuster: User, senior: User, auth_header
):
    headers = auth_header(adjuster)
    claim = await submit(client, headers)
    await move(client, headers, claim["id"], "under_review")

    mine = (await client.get("/claims?mine=true", headers=headers)).json()
    theirs = (await client.get("/claims?mine=true", headers=auth_header(senior))).json()

    assert mine["total"] == 1
    assert theirs["total"] == 0


@pytest.mark.parametrize("offset,expected", [(0, 2), (2, 1)])
async def test_pagination(
    client: AsyncClient, policy: Policy, adjuster: User, auth_header, offset, expected
):
    headers = auth_header(adjuster)
    for _ in range(3):
        await submit(client, headers)

    page = (await client.get(f"/claims?limit=2&offset={offset}", headers=headers)).json()

    assert page["total"] == 3
    assert len(page["items"]) == expected
