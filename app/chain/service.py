from dataclasses import dataclass
from typing import Any

import httpx
from eth_hash.auto import keccak

from app.core.config import Settings


class ChainReadError(RuntimeError):
    """Raised when Arc RPC or the configured contract cannot be read."""


@dataclass(frozen=True)
class VerifiedEvent:
    transaction_hash: str
    block_number: int
    block_hash: str
    log_index: int
    sender: str
    event_name: str
    decoded_data: dict[str, object]


def _selector(signature: str) -> str:
    return "0x" + keccak(signature.encode())[:4].hex()


def _address_argument(address: str) -> str:
    clean = address.removeprefix("0x")
    if len(clean) != 40:
        raise ChainReadError("Configured token address is invalid")
    return clean.rjust(64, "0")


def _decode_uint(value: str) -> int:
    return int(value, 16)


def _decode_address(value: str) -> str:
    return "0x" + value.removeprefix("0x")[-40:]


async def _rpc_batch(
    client: httpx.AsyncClient,
    calls: list[tuple[str, list[Any]]],
) -> list[Any]:
    response = await client.post(
        "",
        json=[
            {"jsonrpc": "2.0", "id": index, "method": method, "params": params}
            for index, (method, params) in enumerate(calls, start=1)
        ],
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ChainReadError("Arc RPC does not support batch reads")
    ordered = sorted(payload, key=lambda item: item.get("id", 0))
    results: list[Any] = []
    for index, item in enumerate(ordered):
        if "error" in item:
            method = calls[index][0]
            message = item["error"].get("message", "unknown RPC error")
            raise ChainReadError(f"Arc RPC rejected {method}: {message}")
        results.append(item["result"])
    return results


async def _read_endpoint(
    rpc_url: str,
    escrow: str,
    token_address: str,
) -> tuple[str, str, str, str, str, str]:
    async with httpx.AsyncClient(
        base_url=rpc_url,
        timeout=httpx.Timeout(10.0),
    ) as client:
        values = await _rpc_batch(
            client,
            [
                ("eth_chainId", []),
                ("eth_getCode", [escrow, "latest"]),
                ("eth_call", [{"to": escrow, "data": _selector("treasury()")}, "latest"]),
                (
                    "eth_call",
                    [{"to": escrow, "data": _selector("fundingFeeBps()")}, "latest"],
                ),
                (
                    "eth_call",
                    [{"to": escrow, "data": _selector("releaseFeeBps()")}, "latest"],
                ),
                (
                    "eth_call",
                    [
                        {
                            "to": escrow,
                            "data": _selector("supportedToken(address)")
                            + _address_argument(token_address),
                        },
                        "latest",
                    ],
                ),
            ],
        )
    if len(values) != 6 or not all(isinstance(value, str) for value in values):
        raise ChainReadError("Arc RPC returned an invalid contract result")
    return tuple(values)


async def read_contract_status(settings: Settings) -> dict[str, object]:
    escrow = settings.arcscrow_escrow_address
    token_registry = settings.token_registry_address
    if not escrow or not token_registry:
        raise ChainReadError("Contract addresses are not configured")

    rpc_urls = [settings.arc_rpc_url, *settings.arc_rpc_fallback_urls]
    last_error: Exception | None = None
    active_rpc_url = settings.arc_rpc_url
    for rpc_url in dict.fromkeys(rpc_urls):
        try:
            (
                chain_id_hex,
                code,
                treasury,
                funding_fee,
                release_fee,
                token_supported,
            ) = await _read_endpoint(rpc_url, escrow, settings.arc_usdc_address)
            active_rpc_url = rpc_url
            break
        except (httpx.HTTPError, ChainReadError, KeyError, TypeError, ValueError) as exc:
            last_error = exc
    else:
        raise ChainReadError(f"Unable to read Arc testnet from configured providers: {last_error}")

    chain_id = _decode_uint(chain_id_hex)
    if chain_id != settings.arc_chain_id:
        raise ChainReadError(
            f"RPC chain ID {chain_id} does not match configured {settings.arc_chain_id}"
        )
    if code in {"0x", "0x0", ""}:
        raise ChainReadError("No contract bytecode exists at the configured escrow address")

    return {
        "network": "Arc Testnet",
        "chain_id": chain_id,
        "rpc_url": active_rpc_url,
        "explorer_url": settings.arc_explorer_url,
        "escrow_address": escrow,
        "token_registry_address": token_registry,
        "token_registry_mode": (
            "escrow-integrated" if token_registry.lower() == escrow.lower() else "separate"
        ),
        "settlement_token": settings.arc_usdc_address,
        "settlement_token_supported": bool(_decode_uint(token_supported)),
        "treasury": _decode_address(treasury),
        "funding_fee_bps": _decode_uint(funding_fee),
        "release_fee_bps": _decode_uint(release_fee),
        "contract_code_bytes": (len(code.removeprefix("0x")) // 2),
    }


async def verify_contract_event(
    settings: Settings,
    *,
    transaction_hash: str,
    event_name: str,
    event_signature: str,
    deal_id: str,
    milestone_position: int | None = None,
) -> VerifiedEvent:
    expected_topic = "0x" + keccak(event_signature.encode()).hex()
    expected_deal = deal_id.lower()
    last_error: Exception | None = None
    for rpc_url in dict.fromkeys([settings.arc_rpc_url, *settings.arc_rpc_fallback_urls]):
        try:
            async with httpx.AsyncClient(base_url=rpc_url, timeout=httpx.Timeout(10.0)) as client:
                receipt, transaction, chain_id = await _rpc_batch(
                    client,
                    [
                        ("eth_getTransactionReceipt", [transaction_hash]),
                        ("eth_getTransactionByHash", [transaction_hash]),
                        ("eth_chainId", []),
                    ],
                )
            if int(chain_id, 16) != settings.arc_chain_id:
                raise ChainReadError("Transaction was read from the wrong chain")
            if not receipt or not transaction:
                raise ChainReadError("Transaction is not confirmed")
            if receipt.get("status") != "0x1":
                raise ChainReadError("Transaction reverted")
            if str(transaction.get("to", "")).lower() != settings.arcscrow_escrow_address.lower():
                raise ChainReadError("Transaction did not call the configured escrow")
            for log in receipt.get("logs", []):
                topics = [str(topic).lower() for topic in log.get("topics", [])]
                if (
                    str(log.get("address", "")).lower()
                    != settings.arcscrow_escrow_address.lower()
                    or len(topics) < 2
                    or topics[0] != expected_topic.lower()
                    or topics[1] != expected_deal
                ):
                    continue
                if milestone_position is not None:
                    if len(topics) < 3 or int(topics[2], 16) != milestone_position:
                        continue
                data = str(log.get("data", "0x")).removeprefix("0x")
                words = [data[index : index + 64] for index in range(0, len(data), 64)]
                decoded: dict[str, object] = {
                    "deal_id": deal_id,
                    "sender": str(transaction["from"]).lower(),
                }
                if milestone_position is not None:
                    decoded["milestone_position"] = milestone_position
                if event_name == "DealFunded" and len(words) >= 2:
                    decoded["gross"] = int(words[0], 16)
                    decoded["credited"] = int(words[1], 16)
                if event_name == "MilestoneReleased" and len(words) >= 2:
                    decoded["net"] = int(words[0], 16)
                    decoded["fee"] = int(words[1], 16)
                return VerifiedEvent(
                    transaction_hash=transaction_hash.lower(),
                    block_number=int(receipt["blockNumber"], 16),
                    block_hash=str(receipt["blockHash"]).lower(),
                    log_index=int(log["logIndex"], 16),
                    sender=str(transaction["from"]).lower(),
                    event_name=event_name,
                    decoded_data=decoded,
                )
            raise ChainReadError(f"{event_name} event was not found in the transaction")
        except (httpx.HTTPError, ChainReadError, KeyError, TypeError, ValueError) as exc:
            last_error = exc
    raise ChainReadError(f"Unable to verify Arc transaction: {last_error}")
