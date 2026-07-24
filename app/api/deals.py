from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUser, Db, accessible_deal
from app.api.schemas import DealCreate, DealOut, FundingIn, TransitionIn
from app.db.models import Deal, DealParty, DealRole, DealStatus, Milestone, OutboxEvent
from app.deals.service import InvalidDealTransition, apply_funding, transition, validate_allocations
from app.evidence.service import append_evidence

router = APIRouter(prefix="/deals", tags=["deals"])


@router.get("", response_model=list[DealOut])
async def list_deals(
    user: CurrentUser,
    db: Db,
    status_filter: DealStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Deal]:
    query = (
        select(Deal)
        .join(DealParty)
        .where(DealParty.user_id == user.id)
        .options(selectinload(Deal.parties), selectinload(Deal.milestones))
        .order_by(Deal.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        query = query.where(Deal.status == status_filter)
    return list((await db.scalars(query)).unique())


@router.post("", response_model=DealOut, status_code=status.HTTP_201_CREATED)
async def create_deal(
    payload: DealCreate,
    user: CurrentUser,
    db: Db,
    idempotency_key: str = Header(min_length=8, max_length=100),
) -> Deal:
    existing = await db.scalar(
        select(OutboxEvent).where(
            OutboxEvent.event_type == "deal.created",
            OutboxEvent.payload["idempotency_key"].as_string() == idempotency_key,
        )
    )
    if existing:
        deal = await db.scalar(
            select(Deal)
            .where(Deal.id == UUID(existing.aggregate_id))
            .options(selectinload(Deal.parties), selectinload(Deal.milestones))
        )
        assert deal is not None
        return deal
    try:
        validate_allocations(payload.total_amount, (m.amount for m in payload.milestones))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    deal = Deal(
        title=payload.title,
        description=payload.description,
        deal_type=payload.deal_type,
        creator_id=user.id,
        token_address=payload.token_address.lower(),
        token_symbol=payload.token_symbol,
        token_decimals=payload.token_decimals,
        total_amount=payload.total_amount,
        funding_threshold_bps=payload.funding_threshold_bps,
    )
    deal.parties.append(
        DealParty(user_id=user.id, role=DealRole.BUYER, permissions={"manage": True})
    )
    for position, milestone in enumerate(payload.milestones):
        deal.milestones.append(
            Milestone(
                position=position,
                title=milestone.title,
                description=milestone.description,
                amount=milestone.amount,
                acceptance_criteria=milestone.acceptance_criteria,
                rejection_limit=milestone.rejection_limit,
                due_at=milestone.due_at,
            )
        )
    db.add(deal)
    await db.flush()
    db.add(
        OutboxEvent(
            aggregate_type="deal",
            aggregate_id=str(deal.id),
            event_type="deal.created",
            payload={"deal_id": str(deal.id), "idempotency_key": idempotency_key},
            created_at=datetime.now(UTC),
        )
    )
    await append_evidence(
        db,
        deal_id=deal.id,
        evidence_type="DEAL_CREATED",
        actor_id=user.id,
        source_entity_type="deal",
        source_entity_id=str(deal.id),
        payload={"title": deal.title, "total_amount": deal.total_amount},
    )
    await db.commit()
    return deal


@router.get("/{deal_id}", response_model=DealOut)
async def get_deal(deal: Deal = Depends(accessible_deal)) -> Deal:
    return deal


@router.post("/{deal_id}/transition", response_model=DealOut)
async def change_status(
    payload: TransitionIn,
    user: CurrentUser,
    db: Db,
    deal: Deal = Depends(accessible_deal),
) -> Deal:
    if deal.version != payload.expected_version:
        raise HTTPException(status.HTTP_409_CONFLICT, "Deal changed; refresh before retrying")
    if not any(
        party.user_id == user.id and party.role in {DealRole.BUYER, DealRole.DEAL_ADMIN}
        for party in deal.parties
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Deal manager permission required")
    try:
        transition(deal, payload.status)
    except InvalidDealTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return deal


@router.post("/{deal_id}/funding", response_model=DealOut)
async def record_funding(
    payload: FundingIn,
    user: CurrentUser,
    db: Db,
    deal: Deal = Depends(accessible_deal),
) -> Deal:
    if payload.simulated and payload.transaction_hash:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Simulated funding cannot have a chain hash"
        )
    if not payload.simulated and not payload.transaction_hash:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A real funding record requires a transaction hash"
        )
    try:
        apply_funding(deal, payload.amount)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await append_evidence(
        db,
        deal_id=deal.id,
        evidence_type="FUNDING_RECORDED",
        actor_id=user.id,
        source_entity_type="blockchain_transaction" if not payload.simulated else "demo_event",
        source_entity_id=payload.transaction_hash or f"sim-{deal.version}",
        payload={"amount": payload.amount, "simulated": payload.simulated},
    )
    await db.commit()
    return deal
