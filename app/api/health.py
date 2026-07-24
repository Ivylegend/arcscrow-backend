from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.api.dependencies import Db
from app.core.config import get_settings

router = APIRouter(tags=["operations"])


@router.get("/health")
async def health(db: Db) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "healthy", "service": get_settings().app_name}


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
