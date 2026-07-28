"""Claim business lifecycle rules.

Pure logic: no database, no I/O, no framework types. Callers gather the facts
(current status, actor, amounts) and this module decides whether the move is legal.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.models.claim import ClaimStatus
from app.models.user import UserRole

ALL_ROLES = frozenset(UserRole)
SENIOR_ROLES = frozenset({UserRole.SENIOR_ADJUSTER, UserRole.ADMIN})


class TransitionOutcome(StrEnum):
    ALLOWED = "allowed"
    ILLEGAL = "illegal"
    FORBIDDEN = "forbidden"
    INVALID = "invalid"


@dataclass(frozen=True)
class TransitionRequest:
    from_status: ClaimStatus
    to_status: ClaimStatus
    actor_id: uuid.UUID | None = None
    actor_role: UserRole | None = None
    actor_authority_limit: Decimal = Decimal("0")
    settlement_amount: Decimal | None = None
    escalated_by_id: uuid.UUID | None = None
    is_system: bool = False


@dataclass(frozen=True)
class TransitionResult:
    outcome: TransitionOutcome
    message: str | None = None

    @property
    def allowed(self) -> bool:
        return self.outcome is TransitionOutcome.ALLOWED


@dataclass(frozen=True)
class Guard:
    check: Callable[[TransitionRequest], str | None]
    outcome: TransitionOutcome


def _requires_settlement_amount(request: TransitionRequest) -> str | None:
    if request.settlement_amount is None:
        return "A settlement amount is required for this transition"
    if request.settlement_amount <= 0:
        return "Settlement amount must be greater than zero"
    return None


def _within_authority(request: TransitionRequest) -> str | None:
    if request.settlement_amount is None:
        return None
    if request.settlement_amount > request.actor_authority_limit:
        return (
            f"Settlement amount {request.settlement_amount} exceeds your "
            f"authority limit of {request.actor_authority_limit}"
        )
    return None


def _four_eyes(request: TransitionRequest) -> str | None:
    if request.escalated_by_id is None:
        return None
    if request.actor_id == request.escalated_by_id:
        return "Approval must be given by someone other than the user who escalated the claim"
    return None


REQUIRE_AMOUNT = Guard(_requires_settlement_amount, TransitionOutcome.INVALID)
WITHIN_AUTHORITY = Guard(_within_authority, TransitionOutcome.FORBIDDEN)
FOUR_EYES = Guard(_four_eyes, TransitionOutcome.FORBIDDEN)


@dataclass(frozen=True)
class Transition:
    allowed_roles: frozenset[UserRole] = frozenset()
    guards: tuple[Guard, ...] = ()
    system_only: bool = False


TRANSITIONS: dict[ClaimStatus, dict[ClaimStatus, Transition]] = {
    ClaimStatus.SUBMITTED: {
        ClaimStatus.TRIAGED: Transition(system_only=True),
        ClaimStatus.UNDER_REVIEW: Transition(allowed_roles=ALL_ROLES),
        ClaimStatus.WITHDRAWN: Transition(allowed_roles=ALL_ROLES),
    },
    ClaimStatus.TRIAGED: {
        ClaimStatus.UNDER_REVIEW: Transition(allowed_roles=ALL_ROLES),
        ClaimStatus.WITHDRAWN: Transition(allowed_roles=ALL_ROLES),
    },
    ClaimStatus.UNDER_REVIEW: {
        ClaimStatus.PENDING_APPROVAL: Transition(
            allowed_roles=ALL_ROLES,
            guards=(REQUIRE_AMOUNT,),
        ),
        ClaimStatus.APPROVED: Transition(
            allowed_roles=ALL_ROLES,
            guards=(REQUIRE_AMOUNT, WITHIN_AUTHORITY),
        ),
        ClaimStatus.DENIED: Transition(allowed_roles=ALL_ROLES),
        ClaimStatus.WITHDRAWN: Transition(allowed_roles=ALL_ROLES),
    },
    ClaimStatus.PENDING_APPROVAL: {
        ClaimStatus.APPROVED: Transition(
            allowed_roles=SENIOR_ROLES,
            guards=(REQUIRE_AMOUNT, WITHIN_AUTHORITY, FOUR_EYES),
        ),
        ClaimStatus.UNDER_REVIEW: Transition(allowed_roles=SENIOR_ROLES),
        ClaimStatus.DENIED: Transition(allowed_roles=SENIOR_ROLES),
    },
    ClaimStatus.APPROVED: {
        ClaimStatus.SETTLED: Transition(allowed_roles=ALL_ROLES),
    },
    ClaimStatus.SETTLED: {
        ClaimStatus.UNDER_REVIEW: Transition(allowed_roles=SENIOR_ROLES),
    },
    ClaimStatus.DENIED: {
        ClaimStatus.UNDER_REVIEW: Transition(allowed_roles=SENIOR_ROLES),
    },
    ClaimStatus.WITHDRAWN: {},
}

TERMINAL_STATUSES = frozenset(
    status for status, moves in TRANSITIONS.items() if not moves
)


def evaluate(request: TransitionRequest) -> TransitionResult:
    transition = TRANSITIONS.get(request.from_status, {}).get(request.to_status)

    if transition is None:
        return TransitionResult(
            TransitionOutcome.ILLEGAL,
            f"A claim cannot move from {request.from_status} to {request.to_status}",
        )

    if transition.system_only and not request.is_system:
        return TransitionResult(
            TransitionOutcome.FORBIDDEN,
            "This transition is performed by the system, not by a user",
        )

    if request.is_system and not transition.system_only:
        return TransitionResult(
            TransitionOutcome.FORBIDDEN,
            "This transition requires a user actor",
        )

    if not request.is_system:
        if request.actor_role is None or request.actor_role not in transition.allowed_roles:
            return TransitionResult(
                TransitionOutcome.FORBIDDEN,
                "Your role is not permitted to perform this transition",
            )

    for guard in transition.guards:
        failure = guard.check(request)
        if failure is not None:
            return TransitionResult(guard.outcome, failure)

    return TransitionResult(TransitionOutcome.ALLOWED)


def available_transitions(
    from_status: ClaimStatus, role: UserRole | None
) -> frozenset[ClaimStatus]:
    """Target statuses a given role could attempt. Ignores amount-dependent guards."""
    if role is None:
        return frozenset()
    return frozenset(
        target
        for target, transition in TRANSITIONS.get(from_status, {}).items()
        if not transition.system_only and role in transition.allowed_roles
    )
