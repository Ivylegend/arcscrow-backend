from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import CurrentUser, Db, accessible_deal
from app.api.schemas import (
    AgreementAcceptIn,
    AgreementOut,
    BlockchainEventOut,
    DisputeCreateIn,
    DisputeOut,
    MilestoneOut,
    MilestoneSubmitIn,
    OnchainPrepareOut,
    TransactionIn,
)
from app.chain.service import ChainReadError, VerifiedEvent, verify_contract_event
from app.core.config import get_settings
from app.db.models import (
    AgreementVersion,
    BlockchainEvent,
    Deal,
    DealParty,
    DealRole,
    DealStatus,
    Dispute,
    Milestone,
    MilestoneStatus,
)
from app.evidence.service import append_evidence

router = APIRouter(tags=["deal workflow"])

CONTRACT_ROLES = {
    DealRole.BUYER: 1,
    DealRole.SELLER: 2,
    DealRole.CONTRIBUTOR: 3,
    DealRole.APPROVER: 4,
    DealRole.OBSERVER: 5,
}


def _party(deal: Deal, user_id: UUID) -> DealParty:
    value = next((party for party in deal.parties if party.user_id == user_id), None)
    if value is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Deal membership required")
    return value


def _require_role(deal: Deal, user_id: UUID, roles: set[DealRole]) -> DealParty:
    party = _party(deal, user_id)
    if party.role not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your deal role cannot perform this action")
    return party


async def _milestone(db: Db, deal: Deal, milestone_id: UUID) -> Milestone:
    value = await db.get(Milestone, milestone_id)
    if not value or value.deal_id != deal.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Milestone not found")
    return value


async def _verified(
    *,
    transaction_hash: str,
    event_name: str,
    event_signature: str,
    deal: Deal,
    milestone: Milestone | None = None,
) -> VerifiedEvent:
    assert deal.onchain_deal_id is not None
    try:
        return await verify_contract_event(
            get_settings(),
            transaction_hash=transaction_hash,
            event_name=event_name,
            event_signature=event_signature,
            deal_id=deal.onchain_deal_id,
            milestone_position=milestone.position if milestone else None,
        )
    except ChainReadError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


async def _store_event(db: Db, verified: VerifiedEvent) -> BlockchainEvent:
    existing = await db.scalar(
        select(BlockchainEvent).where(
            BlockchainEvent.chain_id == get_settings().arc_chain_id,
            BlockchainEvent.transaction_hash == verified.transaction_hash,
            BlockchainEvent.log_index == verified.log_index,
        )
    )
    if existing:
        return existing
    event = BlockchainEvent(
        chain_id=get_settings().arc_chain_id,
        contract_address=get_settings().arcscrow_escrow_address.lower(),
        transaction_hash=verified.transaction_hash,
        block_number=verified.block_number,
        block_hash=verified.block_hash,
        log_index=verified.log_index,
        event_name=verified.event_name,
        decoded_data=verified.decoded_data,
        status="CONFIRMED",
        processed_at=datetime.now(UTC),
    )
    db.add(event)
    return event


@router.get("/deals/{deal_id}/agreement", response_model=list[AgreementOut])
async def agreements(
    db: Db,
    deal: Deal = Depends(accessible_deal),
) -> list[AgreementVersion]:
    return list(
        await db.scalars(
            select(AgreementVersion)
            .where(AgreementVersion.deal_id == deal.id)
            .order_by(AgreementVersion.version.desc())
        )
    )


@router.get("/deals/{deal_id}/onchain/prepare", response_model=OnchainPrepareOut)
async def prepare_onchain(
    db: Db,
    deal: Deal = Depends(accessible_deal),
) -> OnchainPrepareOut:
    if not deal.onchain_deal_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Deal has no on-chain identifier")
    agreement = await _latest_agreement(db, deal)
    contract_parties = [
        party
        for party in deal.parties
        if party.role in CONTRACT_ROLES and party.wallet_address is not None
    ]
    if not any(party.role == DealRole.BUYER for party in contract_parties):
        raise HTTPException(status.HTTP_409_CONFLICT, "A linked buyer wallet is required")
    sellers = [party for party in contract_parties if party.role == DealRole.SELLER]
    if len(sellers) != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Exactly one linked seller is required")
    addresses = [party.wallet_address for party in contract_parties]
    assert all(address is not None for address in addresses)
    if len({address.lower() for address in addresses if address}) != len(addresses):
        raise HTTPException(status.HTTP_409_CONFLICT, "Party wallets must be distinct")
    seller = sellers[0].wallet_address
    assert seller is not None
    return OnchainPrepareOut(
        deal_id=deal.onchain_deal_id,
        agreement_hash="0x" + agreement.content_hash,
        token=deal.token_address,
        funding_required=deal.total_amount,
        funding_threshold_bps=deal.funding_threshold_bps,
        parties=[address for address in addresses if address],
        roles=[CONTRACT_ROLES[party.role] for party in contract_parties],
        allocations=[milestone.amount for milestone in sorted(deal.milestones, key=lambda x: x.position)],
        recipients=[seller for _ in deal.milestones],
    )


async def _latest_agreement(db: Db, deal: Deal) -> AgreementVersion:
    value = await db.scalar(
        select(AgreementVersion)
        .where(AgreementVersion.deal_id == deal.id)
        .order_by(AgreementVersion.version.desc())
    )
    if value is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Agreement terms are missing")
    return value


@router.post("/deals/{deal_id}/onchain/register", response_model=BlockchainEventOut)
async def register_onchain(
    payload: TransactionIn,
    user: CurrentUser,
    db: Db,
    deal: Deal = Depends(accessible_deal),
) -> BlockchainEvent:
    buyer = _require_role(deal, user.id, {DealRole.BUYER})
    if not buyer.wallet_address:
        raise HTTPException(status.HTTP_409_CONFLICT, "Link a buyer wallet first")
    verified = await _verified(
        transaction_hash=payload.transaction_hash,
        event_name="DealRegistered",
        event_signature="DealRegistered(bytes32,bytes32,uint32,address)",
        deal=deal,
    )
    if verified.sender != buyer.wallet_address.lower():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Registration sender is not buyer")
    event = await _store_event(db, verified)
    deal.registration_transaction_hash = verified.transaction_hash
    deal.status = DealStatus.AWAITING_SIGNATURES
    deal.version += 1
    await append_evidence(
        db,
        deal_id=deal.id,
        evidence_type="DEAL_REGISTERED",
        actor_id=user.id,
        source_entity_type="blockchain_transaction",
        source_entity_id=verified.transaction_hash,
        payload=verified.decoded_data,
    )
    await db.commit()
    return event


@router.post("/deals/{deal_id}/agreement/accept", response_model=BlockchainEventOut)
async def accept_agreement(
    payload: AgreementAcceptIn,
    user: CurrentUser,
    db: Db,
    deal: Deal = Depends(accessible_deal),
) -> BlockchainEvent:
    party = _party(deal, user.id)
    if not party.wallet_address or not payload.transaction_hash:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A linked party wallet and Arc acceptance transaction are required",
        )
    verified = await _verified(
        transaction_hash=payload.transaction_hash,
        event_name="PartyAccepted",
        event_signature="PartyAccepted(bytes32,address,bytes32,uint32)",
        deal=deal,
    )
    if verified.sender != party.wallet_address.lower():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Acceptance sender mismatch")
    event = await _store_event(db, verified)
    party.accepted_at = datetime.now(UTC)
    party.acceptance_transaction_hash = verified.transaction_hash
    required = [p for p in deal.parties if p.role != DealRole.OBSERVER]
    if all(p.accepted_at is not None for p in required):
        deal.status = DealStatus.AWAITING_FUNDING
    deal.version += 1
    await append_evidence(
        db,
        deal_id=deal.id,
        evidence_type="AGREEMENT_ACCEPTED",
        actor_id=user.id,
        source_entity_type="blockchain_transaction",
        source_entity_id=verified.transaction_hash,
        payload={"wallet_address": party.wallet_address},
    )
    await db.commit()
    return event


@router.post("/deals/{deal_id}/milestones/{milestone_id}/submit", response_model=MilestoneOut)
async def submit_milestone(
    milestone_id: UUID,
    payload: MilestoneSubmitIn,
    user: CurrentUser,
    db: Db,
    deal: Deal = Depends(accessible_deal),
) -> Milestone:
    party = _require_role(deal, user.id, {DealRole.SELLER})
    milestone = await _milestone(db, deal, milestone_id)
    verified = await _verified(
        transaction_hash=payload.transaction_hash,
        event_name="MilestoneSubmitted",
        event_signature="MilestoneSubmitted(bytes32,uint32,bytes32)",
        deal=deal,
        milestone=milestone,
    )
    if verified.sender != (party.wallet_address or "").lower():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Submission sender mismatch")
    await _store_event(db, verified)
    milestone.status = MilestoneStatus.SUBMITTED
    milestone.submission_note = payload.note
    milestone.submission_hash = payload.evidence_hash.lower()
    milestone.submission_transaction_hash = verified.transaction_hash
    deal.status = DealStatus.MILESTONE_REVIEW
    deal.version += 1
    await append_evidence(
        db,
        deal_id=deal.id,
        evidence_type="MILESTONE_SUBMITTED",
        actor_id=user.id,
        source_entity_type="blockchain_transaction",
        source_entity_id=verified.transaction_hash,
        payload={"milestone_id": str(milestone.id), "evidence_hash": payload.evidence_hash},
    )
    await db.commit()
    return milestone


@router.post("/deals/{deal_id}/milestones/{milestone_id}/approve", response_model=MilestoneOut)
async def approve_milestone(
    milestone_id: UUID,
    payload: TransactionIn,
    user: CurrentUser,
    db: Db,
    deal: Deal = Depends(accessible_deal),
) -> Milestone:
    party = _require_role(deal, user.id, {DealRole.BUYER, DealRole.APPROVER})
    milestone = await _milestone(db, deal, milestone_id)
    verified = await _verified(
        transaction_hash=payload.transaction_hash,
        event_name="MilestoneApproved",
        event_signature="MilestoneApproved(bytes32,uint32,address)",
        deal=deal,
        milestone=milestone,
    )
    if verified.sender != (party.wallet_address or "").lower():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Approval sender mismatch")
    await _store_event(db, verified)
    milestone.status = MilestoneStatus.APPROVED
    milestone.approval_transaction_hash = verified.transaction_hash
    deal.version += 1
    await db.commit()
    return milestone


@router.post("/deals/{deal_id}/milestones/{milestone_id}/release", response_model=MilestoneOut)
async def release_milestone(
    milestone_id: UUID,
    payload: TransactionIn,
    user: CurrentUser,
    db: Db,
    deal: Deal = Depends(accessible_deal),
) -> Milestone:
    _require_role(deal, user.id, {DealRole.BUYER, DealRole.DEAL_ADMIN})
    milestone = await _milestone(db, deal, milestone_id)
    verified = await _verified(
        transaction_hash=payload.transaction_hash,
        event_name="MilestoneReleased",
        event_signature="MilestoneReleased(bytes32,uint32,address,uint256,uint256)",
        deal=deal,
        milestone=milestone,
    )
    await _store_event(db, verified)
    milestone.status = MilestoneStatus.RELEASED
    milestone.released_amount = milestone.amount
    milestone.release_transaction_hash = verified.transaction_hash
    deal.released_amount += milestone.amount
    if deal.released_amount + deal.refunded_amount >= deal.total_amount:
        deal.status = DealStatus.COMPLETED
    else:
        deal.status = DealStatus.ACTIVE
    deal.version += 1
    await append_evidence(
        db,
        deal_id=deal.id,
        evidence_type="MILESTONE_RELEASED",
        actor_id=user.id,
        source_entity_type="blockchain_transaction",
        source_entity_id=verified.transaction_hash,
        payload={"milestone_id": str(milestone.id), **verified.decoded_data},
    )
    await db.commit()
    return milestone


@router.post("/deals/{deal_id}/milestones/{milestone_id}/disputes", response_model=DisputeOut)
async def open_dispute(
    milestone_id: UUID,
    payload: DisputeCreateIn,
    user: CurrentUser,
    db: Db,
    deal: Deal = Depends(accessible_deal),
) -> Dispute:
    party = _party(deal, user.id)
    milestone = await _milestone(db, deal, milestone_id)
    verified = await _verified(
        transaction_hash=payload.transaction_hash,
        event_name="DisputeOpened",
        event_signature="DisputeOpened(bytes32,uint32,bytes32)",
        deal=deal,
        milestone=milestone,
    )
    if verified.sender != (party.wallet_address or "").lower():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Dispute sender mismatch")
    await _store_event(db, verified)
    dispute = Dispute(
        deal_id=deal.id,
        milestone_id=milestone.id,
        opened_by=user.id,
        reason=payload.reason,
        requested_outcome=payload.requested_outcome,
    )
    db.add(dispute)
    milestone.status = MilestoneStatus.DISPUTED
    deal.status = DealStatus.DISPUTED
    deal.disputed_amount += milestone.amount
    deal.version += 1
    await db.commit()
    return dispute


@router.get("/deals/{deal_id}/disputes", response_model=list[DisputeOut])
async def disputes(db: Db, deal: Deal = Depends(accessible_deal)) -> list[Dispute]:
    return list(
        await db.scalars(
            select(Dispute).where(Dispute.deal_id == deal.id).order_by(Dispute.created_at.desc())
        )
    )


@router.get("/deals/{deal_id}/transactions", response_model=list[BlockchainEventOut])
async def transactions(db: Db, deal: Deal = Depends(accessible_deal)) -> list[BlockchainEvent]:
    if not deal.onchain_deal_id:
        return []
    return list(
        await db.scalars(
            select(BlockchainEvent)
            .where(
                BlockchainEvent.decoded_data["deal_id"].as_string() == deal.onchain_deal_id
            )
            .order_by(BlockchainEvent.block_number.desc(), BlockchainEvent.log_index.desc())
        )
    )
