from collections.abc import Iterable

from app.db.models import Deal, DealStatus

TRANSITIONS: dict[DealStatus, frozenset[DealStatus]] = {
    DealStatus.DRAFT: frozenset({DealStatus.NEGOTIATING, DealStatus.AWAITING_PARTIES}),
    DealStatus.NEGOTIATING: frozenset(
        {DealStatus.AWAITING_PARTIES, DealStatus.AWAITING_SIGNATURES}
    ),
    DealStatus.AWAITING_PARTIES: frozenset(
        {DealStatus.NEGOTIATING, DealStatus.AWAITING_SIGNATURES, DealStatus.EXPIRED}
    ),
    DealStatus.AWAITING_SIGNATURES: frozenset(
        {DealStatus.NEGOTIATING, DealStatus.AWAITING_FUNDING, DealStatus.EXPIRED}
    ),
    DealStatus.AWAITING_FUNDING: frozenset(
        {DealStatus.PARTIALLY_FUNDED, DealStatus.READY_TO_START, DealStatus.CANCELLATION_REQUESTED}
    ),
    DealStatus.PARTIALLY_FUNDED: frozenset(
        {DealStatus.READY_TO_START, DealStatus.CANCELLATION_REQUESTED}
    ),
    DealStatus.READY_TO_START: frozenset({DealStatus.ACTIVE, DealStatus.CANCELLATION_REQUESTED}),
    DealStatus.ACTIVE: frozenset(
        {
            DealStatus.MILESTONE_REVIEW,
            DealStatus.DISPUTED,
            DealStatus.COMPLETED,
            DealStatus.CANCELLATION_REQUESTED,
        }
    ),
    DealStatus.MILESTONE_REVIEW: frozenset(
        {DealStatus.ACTIVE, DealStatus.DISPUTED, DealStatus.COMPLETED}
    ),
    DealStatus.DISPUTED: frozenset({DealStatus.ACTIVE, DealStatus.COMPLETED, DealStatus.CANCELLED}),
    DealStatus.CANCELLATION_REQUESTED: frozenset({DealStatus.ACTIVE, DealStatus.CANCELLED}),
    DealStatus.COMPLETED: frozenset({DealStatus.ARCHIVED}),
    DealStatus.CANCELLED: frozenset({DealStatus.ARCHIVED}),
    DealStatus.EXPIRED: frozenset({DealStatus.ARCHIVED}),
    DealStatus.ARCHIVED: frozenset(),
}


class InvalidDealTransition(ValueError):
    pass


def transition(deal: Deal, target: DealStatus) -> None:
    if target not in TRANSITIONS[deal.status]:
        raise InvalidDealTransition(f"Cannot transition deal from {deal.status} to {target}")
    deal.status = target
    deal.version += 1


def apply_funding(deal: Deal, amount: int) -> None:
    if amount <= 0:
        raise ValueError("Funding amount must be positive")
    if deal.funded_amount + amount > deal.total_amount:
        raise ValueError("Funding exceeds required value")
    deal.funded_amount += amount
    threshold_reached = (
        deal.funded_amount * 10_000 >= deal.total_amount * deal.funding_threshold_bps
    )
    deal.status = DealStatus.ACTIVE if threshold_reached else DealStatus.PARTIALLY_FUNDED
    deal.version += 1


def validate_allocations(total: int, allocations: Iterable[int]) -> None:
    values = list(allocations)
    if not values or any(value <= 0 for value in values) or sum(values) != total:
        raise ValueError("Milestone allocations must be positive and equal the deal total")
