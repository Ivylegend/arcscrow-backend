from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencies import CurrentUser, Db, accessible_deal
from app.api.schemas import EvidenceOut
from app.db.models import Deal, EvidenceItem

router = APIRouter(prefix="/deals/{deal_id}/evidence", tags=["evidence"])


@router.get("", response_model=list[EvidenceOut])
async def list_evidence(
    deal_id: UUID,
    db: Db,
    user: CurrentUser,
    deal: Deal = Depends(accessible_deal),
) -> list[EvidenceItem]:
    del user
    assert deal.id == deal_id
    return list(
        await db.scalars(
            select(EvidenceItem)
            .where(EvidenceItem.deal_id == deal_id)
            .order_by(EvidenceItem.occurred_at, EvidenceItem.id)
        )
    )
