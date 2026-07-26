from datetime import UTC, datetime
from uuid import UUID

from eth_hash.auto import keccak
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUser, Db, accessible_deal
from app.api.schemas import DealCreate, DealOut, FundingIn, TransitionIn
from app.db.models import (
    AgreementVersion,
    Deal,
    DealParty,
    DealRole,
    DealStatus,
    Milestone,
    OutboxEvent,
    WalletIdentity,
)
from app.deals.service import InvalidDealTransition, apply_funding, transition, validate_allocations
from app.evidence.service import append_evidence, canonical_json

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
    buyer_wallet = payload.buyer_wallet_address.lower() if payload.buyer_wallet_address else None
    if buyer_wallet:
        identity = await db.scalar(
            select(WalletIdentity).where(
                WalletIdentity.user_id == user.id,
                WalletIdentity.address == buyer_wallet,
            )
        )
        if not identity:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Link the buyer wallet to your account before creating this deal",
            )
    terms = payload.model_dump(
        mode="json",
        exclude={"buyer_wallet_address", "seller_email", "seller_wallet_address"},
    )
    agreement_hash = keccak(canonical_json(terms)).hex()
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
        DealParty(
            user_id=user.id,
            role=DealRole.BUYER,
            permissions={"manage": True},
            wallet_address=buyer_wallet,
        )
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
    deal.onchain_deal_id = "0x" + keccak(str(deal.id).encode()).hex()
    db.add(
        AgreementVersion(
            deal_id=deal.id,
            version=1,
            structured_terms=terms,
            content_hash=agreement_hash,
            created_by=user.id,
        )
    )
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
    if payload.simulated:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Simulated funding is not supported"
        )
    if not payload.transaction_hash:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A real funding record requires a transaction hash"
        )
    from app.api.workflow import _store_event, _verified

    verified = await _verified(
        transaction_hash=payload.transaction_hash,
        event_name="DealFunded",
        event_signature="DealFunded(bytes32,address,uint256,uint256)",
        deal=deal,
    )
    credited = verified.decoded_data.get("credited")
    if not isinstance(credited, int) or credited != payload.amount:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Funding amount does not match the confirmed Arc event",
        )
    await _store_event(db, verified)
    try:
        apply_funding(deal, payload.amount)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await append_evidence(
        db,
        deal_id=deal.id,
        evidence_type="FUNDING_RECORDED",
        actor_id=user.id,
        source_entity_type="blockchain_transaction",
        source_entity_id=payload.transaction_hash,
        payload={"amount": payload.amount, "sender": verified.sender},
    )
    await db.commit()
    return deal
