import uuid
from decimal import Decimal

import pytest

from app.models.claim import ClaimStatus
from app.models.user import UserRole
from app.services.claim_state_machine import (
    TRANSITIONS,
    TransitionOutcome,
    TransitionRequest,
    available_transitions,
    evaluate,
)

ADJUSTER_ID = uuid.uuid4()
SENIOR_ID = uuid.uuid4()


def req(from_status, to_status, **kwargs) -> TransitionRequest:
    defaults = {
        "actor_id": ADJUSTER_ID,
        "actor_role": UserRole.ADJUSTER,
        "actor_authority_limit": Decimal("50000.00"),
    }
    defaults.update(kwargs)
    return TransitionRequest(from_status=from_status, to_status=to_status, **defaults)


LEGAL_USER_MOVES = [
    (from_status, to_status)
    for from_status, moves in TRANSITIONS.items()
    for to_status, transition in moves.items()
    if not transition.system_only
]


@pytest.mark.parametrize(("from_status", "to_status"), LEGAL_USER_MOVES)
def test_every_legal_move_is_reachable_by_some_role(from_status, to_status):
    """Each non-system transition must be permitted for at least one role."""
    outcomes = {
        role: evaluate(
            req(
                from_status,
                to_status,
                actor_role=role,
                actor_id=SENIOR_ID,
                settlement_amount=Decimal("1000.00"),
                actor_authority_limit=Decimal("999999.00"),
            )
        ).outcome
        for role in UserRole
    }
    assert TransitionOutcome.ALLOWED in outcomes.values()


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (ClaimStatus.SUBMITTED, ClaimStatus.APPROVED),
        (ClaimStatus.SUBMITTED, ClaimStatus.SETTLED),
        (ClaimStatus.TRIAGED, ClaimStatus.APPROVED),
        (ClaimStatus.UNDER_REVIEW, ClaimStatus.SETTLED),
        (ClaimStatus.APPROVED, ClaimStatus.DENIED),
        (ClaimStatus.WITHDRAWN, ClaimStatus.UNDER_REVIEW),
        (ClaimStatus.SETTLED, ClaimStatus.APPROVED),
    ],
)
def test_illegal_moves_are_rejected(from_status, to_status):
    result = evaluate(req(from_status, to_status, actor_role=UserRole.ADMIN))
    assert result.outcome is TransitionOutcome.ILLEGAL


def test_same_status_is_illegal():
    result = evaluate(req(ClaimStatus.UNDER_REVIEW, ClaimStatus.UNDER_REVIEW))
    assert result.outcome is TransitionOutcome.ILLEGAL


def test_withdrawn_is_terminal():
    assert TRANSITIONS[ClaimStatus.WITHDRAWN] == {}


def test_system_performs_triage():
    result = evaluate(
        TransitionRequest(
            from_status=ClaimStatus.SUBMITTED,
            to_status=ClaimStatus.TRIAGED,
            is_system=True,
        )
    )
    assert result.allowed


def test_user_cannot_perform_triage():
    result = evaluate(req(ClaimStatus.SUBMITTED, ClaimStatus.TRIAGED, actor_role=UserRole.ADMIN))
    assert result.outcome is TransitionOutcome.FORBIDDEN


def test_system_cannot_perform_user_transitions():
    result = evaluate(
        TransitionRequest(
            from_status=ClaimStatus.UNDER_REVIEW,
            to_status=ClaimStatus.DENIED,
            is_system=True,
        )
    )
    assert result.outcome is TransitionOutcome.FORBIDDEN


def test_submitted_to_under_review_bypasses_triage():
    """Degradation path: the claim stays workable when the AI pipeline fails."""
    assert evaluate(req(ClaimStatus.SUBMITTED, ClaimStatus.UNDER_REVIEW)).allowed


def test_adjuster_approves_within_authority():
    result = evaluate(
        req(
            ClaimStatus.UNDER_REVIEW,
            ClaimStatus.APPROVED,
            settlement_amount=Decimal("49999.99"),
            actor_authority_limit=Decimal("50000.00"),
        )
    )
    assert result.allowed


def test_adjuster_cannot_approve_above_authority():
    result = evaluate(
        req(
            ClaimStatus.UNDER_REVIEW,
            ClaimStatus.APPROVED,
            settlement_amount=Decimal("50000.01"),
            actor_authority_limit=Decimal("50000.00"),
        )
    )
    assert result.outcome is TransitionOutcome.FORBIDDEN
    assert "authority limit" in result.message


def test_authority_boundary_is_inclusive():
    result = evaluate(
        req(
            ClaimStatus.UNDER_REVIEW,
            ClaimStatus.APPROVED,
            settlement_amount=Decimal("50000.00"),
            actor_authority_limit=Decimal("50000.00"),
        )
    )
    assert result.allowed


def test_approval_requires_settlement_amount():
    result = evaluate(req(ClaimStatus.UNDER_REVIEW, ClaimStatus.APPROVED))
    assert result.outcome is TransitionOutcome.INVALID


def test_escalation_requires_settlement_amount():
    result = evaluate(req(ClaimStatus.UNDER_REVIEW, ClaimStatus.PENDING_APPROVAL))
    assert result.outcome is TransitionOutcome.INVALID


def test_zero_settlement_amount_is_invalid():
    result = evaluate(
        req(
            ClaimStatus.UNDER_REVIEW,
            ClaimStatus.APPROVED,
            settlement_amount=Decimal("0"),
        )
    )
    assert result.outcome is TransitionOutcome.INVALID


def test_adjuster_cannot_approve_escalated_claim():
    result = evaluate(
        req(
            ClaimStatus.PENDING_APPROVAL,
            ClaimStatus.APPROVED,
            settlement_amount=Decimal("100000.00"),
            actor_authority_limit=Decimal("999999.00"),
        )
    )
    assert result.outcome is TransitionOutcome.FORBIDDEN


def test_senior_approves_escalated_claim():
    result = evaluate(
        req(
            ClaimStatus.PENDING_APPROVAL,
            ClaimStatus.APPROVED,
            actor_id=SENIOR_ID,
            actor_role=UserRole.SENIOR_ADJUSTER,
            actor_authority_limit=Decimal("500000.00"),
            settlement_amount=Decimal("100000.00"),
            escalated_by_id=ADJUSTER_ID,
        )
    )
    assert result.allowed


def test_escalator_cannot_approve_their_own_claim():
    result = evaluate(
        req(
            ClaimStatus.PENDING_APPROVAL,
            ClaimStatus.APPROVED,
            actor_id=SENIOR_ID,
            actor_role=UserRole.SENIOR_ADJUSTER,
            actor_authority_limit=Decimal("500000.00"),
            settlement_amount=Decimal("100000.00"),
            escalated_by_id=SENIOR_ID,
        )
    )
    assert result.outcome is TransitionOutcome.FORBIDDEN
    assert "other than" in result.message


def test_senior_still_bound_by_own_authority_limit():
    result = evaluate(
        req(
            ClaimStatus.PENDING_APPROVAL,
            ClaimStatus.APPROVED,
            actor_id=SENIOR_ID,
            actor_role=UserRole.SENIOR_ADJUSTER,
            actor_authority_limit=Decimal("500000.00"),
            settlement_amount=Decimal("500000.01"),
            escalated_by_id=ADJUSTER_ID,
        )
    )
    assert result.outcome is TransitionOutcome.FORBIDDEN


def test_adjuster_cannot_reopen_settled_claim():
    result = evaluate(req(ClaimStatus.SETTLED, ClaimStatus.UNDER_REVIEW))
    assert result.outcome is TransitionOutcome.FORBIDDEN


def test_senior_reopens_settled_claim():
    result = evaluate(
        req(
            ClaimStatus.SETTLED,
            ClaimStatus.UNDER_REVIEW,
            actor_role=UserRole.SENIOR_ADJUSTER,
        )
    )
    assert result.allowed


def test_senior_reopens_denied_claim():
    result = evaluate(
        req(ClaimStatus.DENIED, ClaimStatus.UNDER_REVIEW, actor_role=UserRole.SENIOR_ADJUSTER)
    )
    assert result.allowed


def test_available_transitions_hides_senior_only_moves_from_adjuster():
    assert available_transitions(ClaimStatus.SETTLED, UserRole.ADJUSTER) == frozenset()
    assert available_transitions(ClaimStatus.SETTLED, UserRole.SENIOR_ADJUSTER) == {
        ClaimStatus.UNDER_REVIEW
    }


def test_available_transitions_excludes_system_moves():
    assert ClaimStatus.TRIAGED not in available_transitions(ClaimStatus.SUBMITTED, UserRole.ADMIN)
