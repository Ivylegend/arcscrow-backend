import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2 import PasswordHasher
from eth_account import Account
from eth_account.messages import encode_defunct
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import get_settings

password_hasher = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=4)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    return password_hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except Exception:
        return False


def random_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(user_id: UUID, session_id: UUID) -> str:
    serializer = URLSafeTimedSerializer(get_settings().session_secret, salt="arcscrow-session")
    return serializer.dumps({"sub": str(user_id), "sid": str(session_id)})


def read_session(token: str, max_age: int = 900) -> tuple[UUID, UUID] | None:
    serializer = URLSafeTimedSerializer(get_settings().session_secret, salt="arcscrow-session")
    try:
        data = serializer.loads(token, max_age=max_age)
        return UUID(data["sub"]), UUID(data["sid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError):
        return None


def siwe_message(
    *,
    domain: str,
    address: str,
    nonce: str,
    chain_id: int,
    issued_at: datetime | None = None,
) -> str:
    issued = (issued_at or datetime.now(UTC)).isoformat()
    return (
        f"{domain} wants you to sign in with your Ethereum account:\n{address}\n\n"
        "Sign in to Arcscrow. This request does not initiate a transaction.\n\n"
        f"URI: https://{domain}\nVersion: 1\nChain ID: {chain_id}\n"
        f"Nonce: {nonce}\nIssued At: {issued}\n"
        f"Expiration Time: {(datetime.now(UTC) + timedelta(minutes=10)).isoformat()}"
    )


def recover_wallet(message: str, signature: str) -> str:
    return str(Account.recover_message(encode_defunct(text=message), signature=signature)).lower()
