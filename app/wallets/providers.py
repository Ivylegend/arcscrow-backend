from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx

from app.core.config import get_settings


@dataclass(frozen=True)
class EmbeddedWalletResult:
    provider_id: str
    address: str
    mode: str
    simulated: bool


class EmbeddedWalletProvider(Protocol):
    async def create_wallet(self, *, user_id: UUID) -> EmbeddedWalletResult: ...
    async def get_wallet(self, *, provider_id: str) -> EmbeddedWalletResult: ...
    async def initiate_transaction(
        self, *, provider_id: str, payload: dict[str, object]
    ) -> str: ...
    async def get_transaction_status(self, *, transaction_id: str) -> str: ...


class CircleWalletProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def create_wallet(self, *, user_id: UUID) -> EmbeddedWalletResult:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.circle.com/v1/w3s/user/wallets",
                headers={"Authorization": f"Bearer {self.settings.circle_api_key}"},
                json={
                    "userId": str(user_id),
                    "accountType": "SCA",
                    "blockchains": ["ARC-TESTNET"],
                },
            )
            response.raise_for_status()
            wallet = response.json()["data"]["wallets"][0]
            return EmbeddedWalletResult(wallet["id"], wallet["address"], "user-controlled", False)

    async def get_wallet(self, *, provider_id: str) -> EmbeddedWalletResult:
        raise NotImplementedError(
            "Use Circle notification reconciliation for persisted wallet state"
        )

    async def initiate_transaction(self, *, provider_id: str, payload: dict[str, object]) -> str:
        raise NotImplementedError(
            "User-controlled Circle transaction challenge must be completed client-side"
        )

    async def get_transaction_status(self, *, transaction_id: str) -> str:
        raise NotImplementedError(
            "Circle transaction polling requires configured notification reconciliation"
        )


def get_wallet_provider() -> EmbeddedWalletProvider | None:
    settings = get_settings()
    if settings.circle_embedded_wallet_enabled and settings.circle_api_key:
        return CircleWalletProvider()
    return None
