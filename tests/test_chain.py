from app.api import chain


async def test_contract_status_returns_verified_chain_configuration(client, monkeypatch):
    expected = {
        "network": "Arc Testnet",
        "chain_id": 5_042_002,
        "escrow_address": "0xF050774dCD264C3b8C027944696811c9bc0C5212",
        "settlement_token_supported": True,
    }

    async def fake_status(settings):
        del settings
        return expected

    monkeypatch.setattr(chain, "read_contract_status", fake_status)
    response = await client.get("/api/v1/chain/status")

    assert response.status_code == 200
    assert response.json() == expected


async def test_contract_status_reports_rpc_failure(client, monkeypatch):
    from app.chain.service import ChainReadError

    async def fail(settings):
        del settings
        raise ChainReadError("Arc RPC unavailable")

    monkeypatch.setattr(chain, "read_contract_status", fail)
    response = await client.get("/api/v1/chain/status")

    assert response.status_code == 503
    assert response.json()["detail"] == "Arc RPC unavailable"
