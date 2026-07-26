from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select

from app.api.dependencies import CurrentUser, Db
from app.api.schemas import (
    EvidenceOut,
    NotificationOut,
    OrganisationCreate,
    OrganisationOut,
    ProfileUpdate,
    UserOut,
    WalletIdentityOut,
)
from app.db.models import (
    DealParty,
    EvidenceItem,
    Notification,
    Organisation,
    OrganisationMember,
    User,
    WalletIdentity,
)

router = APIRouter(tags=["workspace"])


@router.get("/wallets", response_model=list[WalletIdentityOut])
async def wallets(user: CurrentUser, db: Db) -> list[WalletIdentity]:
    return list(
        await db.scalars(
            select(WalletIdentity)
            .where(WalletIdentity.user_id == user.id)
            .order_by(WalletIdentity.created_at.desc())
        )
    )


@router.get("/notifications", response_model=list[NotificationOut])
async def notifications(user: CurrentUser, db: Db) -> list[Notification]:
    return list(
        await db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(100)
        )
    )


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
async def read_notification(
    notification_id: UUID,
    user: CurrentUser,
    db: Db,
) -> Notification:
    notification = await db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    notification.read_at = datetime.now(UTC)
    await db.commit()
    return notification


@router.get("/activity", response_model=list[EvidenceOut])
async def activity(user: CurrentUser, db: Db) -> list[EvidenceItem]:
    return list(
        (
            await db.scalars(
                select(EvidenceItem)
                .join(DealParty, DealParty.deal_id == EvidenceItem.deal_id)
                .where(DealParty.user_id == user.id)
                .order_by(EvidenceItem.occurred_at.desc())
                .limit(100)
            )
        ).unique()
    )


@router.patch("/profile", response_model=UserOut)
async def update_profile(payload: ProfileUpdate, user: CurrentUser, db: Db) -> User:
    user.display_name = payload.display_name.strip()
    await db.commit()
    return user


@router.get("/organisations", response_model=list[OrganisationOut])
async def organisations(user: CurrentUser, db: Db) -> list[Organisation]:
    member_ids = select(OrganisationMember.organisation_id).where(
        OrganisationMember.user_id == user.id
    )
    return list(
        await db.scalars(
            select(Organisation)
            .where(or_(Organisation.owner_id == user.id, Organisation.id.in_(member_ids)))
            .order_by(Organisation.created_at.desc())
        )
    )


@router.post(
    "/organisations",
    response_model=OrganisationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_organisation(
    payload: OrganisationCreate,
    user: CurrentUser,
    db: Db,
) -> Organisation:
    if await db.scalar(select(Organisation.id).where(Organisation.slug == payload.slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Organisation slug is already in use")
    organisation = Organisation(name=payload.name.strip(), slug=payload.slug, owner_id=user.id)
    db.add(organisation)
    await db.flush()
    db.add(
        OrganisationMember(
            organisation_id=organisation.id,
            user_id=user.id,
            role="OWNER",
        )
    )
    await db.commit()
    return organisation
