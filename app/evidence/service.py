import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvidenceItem


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def evidence_hash(previous_hash: str | None, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    if previous_hash:
        digest.update(bytes.fromhex(previous_hash))
    digest.update(canonical_json(payload))
    return digest.hexdigest()


async def append_evidence(
    db: AsyncSession,
    *,
    deal_id: UUID,
    evidence_type: str,
    actor_id: UUID | None,
    source_entity_type: str,
    source_entity_id: str,
    payload: dict[str, Any],
) -> EvidenceItem:
    previous = await db.scalar(
        select(EvidenceItem)
        .where(EvidenceItem.deal_id == deal_id)
        .order_by(EvidenceItem.occurred_at.desc(), EvidenceItem.id.desc())
        .limit(1)
    )
    occurred_at = datetime.now(UTC)
    content = {
        "deal_id": str(deal_id),
        "type": evidence_type,
        "actor_id": str(actor_id) if actor_id else None,
        "source": {"type": source_entity_type, "id": source_entity_id},
        "payload": payload,
        "occurred_at": occurred_at.isoformat(),
    }
    item = EvidenceItem(
        deal_id=deal_id,
        type=evidence_type,
        actor_id=actor_id,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        content_hash=evidence_hash(previous.content_hash if previous else None, content),
        previous_hash=previous.content_hash if previous else None,
        metadata_json=payload,
        occurred_at=occurred_at,
    )
    db.add(item)
    return item
