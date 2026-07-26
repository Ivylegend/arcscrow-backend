from fastapi import APIRouter, HTTPException, status

from app.chain.service import ChainReadError, read_contract_status
from app.core.config import get_settings

router = APIRouter(prefix="/chain", tags=["chain"])


@router.get("/status")
async def contract_status() -> dict[str, object]:
    try:
        return await read_contract_status(get_settings())
    except ChainReadError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
