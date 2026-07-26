from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencies import Db, accessible_deal
from app.api.schemas import MessageOut
from app.db.models import Deal, DealMessage, MessageRevision

router = APIRouter(prefix="/deals/{deal_id}/messages", tags=["messages"])


@router.get("", response_model=list[MessageOut])
async def list_messages(
    deal_id: UUID,
    db: Db,
    deal: Deal = Depends(accessible_deal),
) -> list[MessageOut]:
    del deal_id
    rows = await db.execute(
        select(DealMessage, MessageRevision)
        .join(
            MessageRevision,
            (MessageRevision.message_id == DealMessage.id)
            & (MessageRevision.revision == DealMessage.current_revision),
        )
        .where(DealMessage.deal_id == deal.id, DealMessage.deleted_at.is_(None))
        .order_by(MessageRevision.created_at.asc())
    )
    return [
        MessageOut(
            id=message.id,
            author_id=message.author_id,
            content=revision.content,
            created_at=revision.created_at,
        )
        for message, revision in rows
    ]
