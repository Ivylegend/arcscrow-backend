from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

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


class DevelopmentWalletProvider:
    async def create_wallet(self, *, user_id: UUID) -> EmbeddedWalletResult:
        suffix = user_id.hex[-40:].rjust(40, "0")
        return EmbeddedWalletResult(f"dev-{uuid4()}", f"0x{suffix}", "development", True)

    async def get_wallet(self, *, provider_id: str) -> EmbeddedWalletResult:
        raise LookupError(f"Development wallet {provider_id} is not persistent")

    async def initiate_transaction(self, *, provider_id: str, payload: dict[str, object]) -> str:
        del provider_id, payload
        raise RuntimeError("Development wallets cannot create on-chain transactions")

    async def get_transaction_status(self, *, transaction_id: str) -> str:
        del transaction_id
        return "SIMULATION_UNAVAILABLE"


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


def get_wallet_provider() -> EmbeddedWalletProvider:
    settings = get_settings()
    if settings.circle_api_key:
        return CircleWalletProvider()
    return DevelopmentWalletProvider()
