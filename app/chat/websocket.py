import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.core.security import read_session
from app.db.models import DealMessage, DealParty, MessageRevision, Session
from app.db.session import SessionFactory

router = APIRouter()
rooms: dict[UUID, set[WebSocket]] = defaultdict(set)


@router.websocket("/ws/deals/{deal_id}")
async def deal_socket(websocket: WebSocket, deal_id: UUID) -> None:
    token = websocket.cookies.get("arcscrow_session") or websocket.query_params.get("token", "")
    parsed = read_session(token)
    if not parsed:
        await websocket.close(status.WS_1008_POLICY_VIOLATION)
        return
    user_id, session_id = parsed
    async with SessionFactory() as db:
        session = await db.get(Session, session_id)
        membership = await db.scalar(
            select(DealParty.id).where(DealParty.deal_id == deal_id, DealParty.user_id == user_id)
        )
        if not session or session.revoked_at or not membership:
            await websocket.close(status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        rooms[deal_id].add(websocket)
        try:
            while True:
                body = json.loads(await websocket.receive_text())
                event_type = body.get("type")
                if event_type == "typing":
                    outbound = {"type": "typing", "user_id": str(user_id)}
                elif event_type == "message":
                    content = str(body.get("content", "")).strip()
                    if not content or len(content) > 10_000:
                        await websocket.send_json({"type": "error", "message": "Invalid message"})
                        continue
                    now = datetime.now(UTC)
                    message = DealMessage(deal_id=deal_id, author_id=user_id)
                    db.add(message)
                    await db.flush()
                    db.add(
                        MessageRevision(
                            message_id=message.id,
                            revision=1,
                            content=content,
                            content_hash=hashlib.sha256(content.encode()).hexdigest(),
                            actor_id=user_id,
                            created_at=now,
                        )
                    )
                    await db.commit()
                    outbound = {
                        "type": "message",
                        "id": str(message.id),
                        "author_id": str(user_id),
                        "content": content,
                        "created_at": now.isoformat(),
                    }
                else:
                    continue
                for peer in list(rooms[deal_id]):
                    await peer.send_json(outbound)
        except WebSocketDisconnect:
            rooms[deal_id].discard(websocket)
