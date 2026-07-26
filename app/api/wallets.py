from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import CurrentUser
from app.wallets.providers import get_wallet_provider

router = APIRouter(prefix="/wallets", tags=["wallets"])


class EmbeddedWalletOut(BaseModel):
    provider_id: str
    address: str
    mode: str
    simulated: bool


@router.post("/embedded", response_model=EmbeddedWalletOut)
async def create_embedded_wallet(user: CurrentUser) -> EmbeddedWalletOut:
    provider = get_wallet_provider()
    if provider is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Embedded wallets are temporarily unavailable; use an external wallet",
        )
    result = await provider.create_wallet(user_id=user.id)
    return EmbeddedWalletOut(**result.__dict__)
