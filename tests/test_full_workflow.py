from uuid import uuid4

from eth_account import Account
from eth_account.messages import encode_defunct
from httpx import ASGITransport, AsyncClient

from app.api import workflow
from app.chain.service import VerifiedEvent
from app.main import app


async def register(client, email: str, name: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "display_name": name,
            "password": "correct-horse-battery-staple",
        },
    )
    assert response.status_code == 201, response.text


async def link_wallet(client):
    account = Account.create()
    nonce = await client.post(
        "/api/v1/auth/wallet/nonce",
        json={"address": account.address, "chain_id": 5_042_002},
    )
    assert nonce.status_code == 200, nonce.text
    message = nonce.json()["message"]
    signature = Account.sign_message(encode_defunct(text=message), account.key).signature.hex()
    linked = await client.post(
        "/api/v1/auth/wallet/link",
        json={"address": account.address, "message": message, "signature": signature},
    )
    assert linked.status_code == 200, linked.text
    return account.address.lower()


async def test_complete_deal_lifecycle_uses_persisted_parties_and_verified_events(
    client, monkeypatch
):
    await register(client, "buyer-flow@example.com", "Buyer Flow")
    buyer_wallet = await link_wallet(client)
    created = await client.post(
        "/api/v1/deals",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "title": "Complete Arc workflow",
            "description": "A complete persisted deal workflow backed by confirmed Arc events.",
            "total_amount": 1_000_000,
            "buyer_wallet_address": buyer_wallet,
            "milestones": [
                {
                    "title": "Complete delivery",
                    "description": "Supply and approve the final delivery.",
                    "amount": 1_000_000,
                    "acceptance_criteria": [{"type": "manual", "label": "Buyer approval"}],
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    deal = created.json()
    milestone = deal["milestones"][0]

    seller_account = Account.create()
    invitation = await client.post(
        f"/api/v1/deals/{deal['id']}/invitations",
        json={
            "email": "seller-flow@example.com",
            "wallet_address": seller_account.address,
            "role": "SELLER",
        },
    )
    assert invitation.status_code == 201, invitation.text

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as seller:
        await register(seller, "seller-flow@example.com", "Seller Flow")
        nonce = await seller.post(
            "/api/v1/auth/wallet/nonce",
            json={"address": seller_account.address, "chain_id": 5_042_002},
        )
        message = nonce.json()["message"]
        signature = Account.sign_message(
            encode_defunct(text=message), seller_account.key
        ).signature.hex()
        assert (
            await seller.post(
                "/api/v1/auth/wallet/link",
                json={
                    "address": seller_account.address,
                    "message": message,
                    "signature": signature,
                },
            )
        ).status_code == 200
        accepted = await seller.post(
            f"/api/v1/invitations/{invitation.json()['id']}/accept",
            json={"wallet_address": seller_account.address},
        )
        assert accepted.status_code == 200, accepted.text

        prepared = await client.get(f"/api/v1/deals/{deal['id']}/onchain/prepare")
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["parties"] == [buyer_wallet, seller_account.address.lower()]

        senders = {
            "11": buyer_wallet,
            "22": buyer_wallet,
            "33": seller_account.address.lower(),
            "44": buyer_wallet,
            "55": seller_account.address.lower(),
            "66": buyer_wallet,
            "77": buyer_wallet,
        }

        async def fake_verified(**kwargs):
            transaction_hash = kwargs["transaction_hash"]
            marker = transaction_hash[2:4]
            decoded = {"deal_id": deal["onchain_deal_id"]}
            if marker == "44":
                decoded.update({"gross": 1_000_000, "credited": 1_000_000})
            return VerifiedEvent(
                transaction_hash=transaction_hash,
                block_number=int(marker, 16),
                block_hash="0x" + "ab" * 32,
                log_index=0,
                sender=senders[marker],
                event_name=kwargs["event_name"],
                decoded_data=decoded,
            )

        monkeypatch.setattr(workflow, "_verified", fake_verified)

        def transaction(marker):
            return {"transaction_hash": "0x" + marker * 32}
        registered = await client.post(
            f"/api/v1/deals/{deal['id']}/onchain/register",
            json=transaction("11"),
        )
        assert registered.status_code == 200, registered.text
        buyer_accept = await client.post(
            f"/api/v1/deals/{deal['id']}/agreement/accept",
            json=transaction("22"),
        )
        assert buyer_accept.status_code == 200, buyer_accept.text
        seller_accept = await seller.post(
            f"/api/v1/deals/{deal['id']}/agreement/accept",
            json=transaction("33"),
        )
        assert seller_accept.status_code == 200, seller_accept.text
        funded = await client.post(
            f"/api/v1/deals/{deal['id']}/funding",
            json={**transaction("44"), "amount": 1_000_000},
        )
        assert funded.status_code == 200, funded.text
        assert funded.json()["status"] == "ACTIVE"
        submitted = await seller.post(
            f"/api/v1/deals/{deal['id']}/milestones/{milestone['id']}/submit",
            json={
                **transaction("55"),
                "note": "Final delivery supplied",
                "evidence_hash": "0x" + "de" * 32,
            },
        )
        assert submitted.status_code == 200, submitted.text
        approved = await client.post(
            f"/api/v1/deals/{deal['id']}/milestones/{milestone['id']}/approve",
            json=transaction("66"),
        )
        assert approved.status_code == 200, approved.text
        released = await client.post(
            f"/api/v1/deals/{deal['id']}/milestones/{milestone['id']}/release",
            json=transaction("77"),
        )
        assert released.status_code == 200, released.text
        assert released.json()["status"] == "RELEASED"

    transactions = await client.get(f"/api/v1/deals/{deal['id']}/transactions")
    assert transactions.status_code == 200, transactions.text
    assert len(transactions.json()) == 7


async def test_ai_deal_suggestion_is_structured(client):
    await register(client, "ai-flow@example.com", "AI Flow")
    response = await client.post(
        "/api/v1/ai/deal-suggestion",
        json={
            "prompt": "Create a milestone agreement for a research report and final presentation."
        },
    )
    assert response.status_code == 200, response.text
    assert sum(item["percentage"] for item in response.json()["milestones"]) == 100
