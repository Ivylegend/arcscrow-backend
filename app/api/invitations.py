from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import CurrentUser, Db, accessible_deal
from app.api.schemas import (
    InvitationAccept,
    InvitationAcceptById,
    InvitationCreate,
    InvitationOut,
)
from app.core.security import random_token, token_hash
from app.db.models import (
    Deal,
    DealInvitation,
    DealParty,
    DealRole,
    DealStatus,
    Notification,
    User,
    WalletIdentity,
)
from app.evidence.service import append_evidence

router = APIRouter(tags=["invitations"])


def _can_manage(deal: Deal, user_id: UUID) -> bool:
    return any(
        party.user_id == user_id
        and party.role in {DealRole.BUYER, DealRole.DEAL_ADMIN}
        for party in deal.parties
    )


@router.get("/deals/{deal_id}/invitations", response_model=list[InvitationOut])
async def list_invitations(
    db: Db,
    user: CurrentUser,
    deal: Deal = Depends(accessible_deal),
) -> list[DealInvitation]:
    if not _can_manage(deal, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Deal manager permission required")
    return list(
        await db.scalars(
            select(DealInvitation)
            .where(DealInvitation.deal_id == deal.id)
            .order_by(DealInvitation.created_at.desc())
        )
    )


@router.post(
    "/deals/{deal_id}/invitations",
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    payload: InvitationCreate,
    db: Db,
    user: CurrentUser,
    deal: Deal = Depends(accessible_deal),
) -> InvitationOut:
    if not _can_manage(deal, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Deal manager permission required")
    if payload.role not in {
        DealRole.SELLER,
        DealRole.CONTRIBUTOR,
        DealRole.APPROVER,
        DealRole.OBSERVER,
    }:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Role cannot be invited")
    email = payload.email.lower()
    existing = await db.scalar(
        select(DealInvitation).where(
            DealInvitation.deal_id == deal.id,
            DealInvitation.email == email,
            DealInvitation.role == payload.role,
        )
    )
    if existing and existing.status == "PENDING":
        raise HTTPException(status.HTTP_409_CONFLICT, "This invitation is already pending")

    raw_token = random_token()
    invitation = DealInvitation(
        deal_id=deal.id,
        invited_by=user.id,
        email=email,
        wallet_address=payload.wallet_address.lower() if payload.wallet_address else None,
        role=payload.role,
        token_hash=token_hash(raw_token),
        status="PENDING",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invitation)
    await db.flush()
    invited_user = await db.scalar(select(User).where(User.email == email))
    if invited_user:
        db.add(
            Notification(
                user_id=invited_user.id,
                kind="DEAL_INVITATION",
                title=f"Invitation to {deal.title}",
                body=f"You were invited as {payload.role.value.lower()}.",
                deep_link="/app/invitations",
            )
        )
    if deal.status in {DealStatus.DRAFT, DealStatus.NEGOTIATING}:
        deal.status = DealStatus.AWAITING_PARTIES
        deal.version += 1
    await append_evidence(
        db,
        deal_id=deal.id,
        evidence_type="PARTY_INVITED",
        actor_id=user.id,
        source_entity_type="deal_invitation",
        source_entity_id=str(invitation.id),
        payload={"email": email, "role": payload.role.value},
    )
    await db.commit()
    return InvitationOut.model_validate(invitation).model_copy(update={"accept_token": raw_token})


@router.get("/invitations", response_model=list[InvitationOut])
async def my_invitations(user: CurrentUser, db: Db) -> list[DealInvitation]:
    if not user.email:
        return []
    return list(
        await db.scalars(
            select(DealInvitation)
            .where(
                DealInvitation.email == user.email.lower(),
                DealInvitation.status == "PENDING",
            )
            .order_by(DealInvitation.created_at.desc())
        )
    )


@router.post("/invitations/accept", response_model=InvitationOut)
async def accept_invitation(
    payload: InvitationAccept,
    user: CurrentUser,
    db: Db,
) -> DealInvitation:
    invitation = await db.scalar(
        select(DealInvitation).where(DealInvitation.token_hash == token_hash(payload.token))
    )
    return await _accept(invitation, payload.wallet_address, user, db)


@router.post("/invitations/{invitation_id}/accept", response_model=InvitationOut)
async def accept_invitation_by_id(
    invitation_id: UUID,
    payload: InvitationAcceptById,
    user: CurrentUser,
    db: Db,
) -> DealInvitation:
    invitation = await db.get(DealInvitation, invitation_id)
    if not invitation:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found")
    return await _accept(invitation, payload.wallet_address, user, db)


async def _accept(
    invitation: DealInvitation | None,
    supplied_wallet: str | None,
    user: CurrentUser,
    db: Db,
) -> DealInvitation:
    now = datetime.now(UTC)
    if not invitation or invitation.status != "PENDING":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation is invalid or already used")
    if invitation.expires_at.replace(tzinfo=UTC) < now:
        invitation.status = "EXPIRED"
        await db.commit()
        raise HTTPException(status.HTTP_410_GONE, "Invitation expired")
    if not user.email or user.email.lower() != invitation.email:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign in with the invited email")

    wallet_address = supplied_wallet or invitation.wallet_address
    if wallet_address:
        wallet_address = wallet_address.lower()
        identity = await db.scalar(
            select(WalletIdentity).where(
                WalletIdentity.user_id == user.id,
                WalletIdentity.address == wallet_address,
            )
        )
        if not identity:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Link the invited wallet to your account before accepting",
            )
    exists = await db.scalar(
        select(DealParty.id).where(
            DealParty.deal_id == invitation.deal_id,
            DealParty.user_id == user.id,
            DealParty.role == invitation.role,
        )
    )
    if not exists:
        db.add(
            DealParty(
                deal_id=invitation.deal_id,
                user_id=user.id,
                role=invitation.role,
                permissions={"participate": True},
                wallet_address=wallet_address,
            )
        )
    invitation.status = "ACCEPTED"
    invitation.accepted_by = user.id
    invitation.accepted_at = now
    deal = await db.get(Deal, invitation.deal_id)
    assert deal is not None
    pending = await db.scalar(
        select(DealInvitation.id).where(
            DealInvitation.deal_id == deal.id,
            DealInvitation.status == "PENDING",
        )
    )
    if pending is None:
        deal.status = DealStatus.AWAITING_SIGNATURES
        deal.version += 1
    await append_evidence(
        db,
        deal_id=deal.id,
        evidence_type="PARTY_JOINED",
        actor_id=user.id,
        source_entity_type="deal_party",
        source_entity_id=str(user.id),
        payload={"role": invitation.role.value, "wallet_address": wallet_address},
    )
    await db.commit()
    return invitation
