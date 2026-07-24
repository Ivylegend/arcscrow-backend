from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.dependencies import CurrentUser, Db
from app.api.schemas import (
    AuthOut,
    LoginIn,
    RegisterIn,
    UserOut,
    WalletNonceIn,
    WalletNonceOut,
    WalletVerifyIn,
)
from app.core.config import get_settings
from app.core.security import (
    hash_password,
    issue_session,
    random_token,
    recover_wallet,
    siwe_message,
    token_hash,
    verify_password,
)
from app.db.models import AuthNonce, Session, User, WalletIdentity

router = APIRouter(prefix="/auth", tags=["auth"])


async def _new_session(db: Db, response: Response, user: User) -> AuthOut:
    refresh = random_token()
    session = Session(
        user_id=user.id,
        refresh_hash=token_hash(refresh),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(session)
    await db.flush()
    access = issue_session(user.id, session.id)
    settings = get_settings()
    response.set_cookie(
        "arcscrow_session",
        access,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=900,
        path="/",
    )
    response.set_cookie(
        "arcscrow_refresh",
        refresh,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=2_592_000,
        path=f"{settings.api_prefix}/auth",
    )
    csrf = random_token()
    response.set_cookie("arcscrow_csrf", csrf, secure=settings.cookie_secure, samesite="lax")
    await db.commit()
    return AuthOut(user=UserOut.model_validate(user), csrf_token=csrf)


@router.post("/register", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterIn, response: Response, db: Db) -> AuthOut:
    email = payload.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")
    user = User(
        email=email,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()
    return await _new_session(db, response, user)


@router.post("/login", response_model=AuthOut)
async def login(payload: LoginIn, response: Response, db: Db) -> AuthOut:
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if (
        not user
        or not user.password_hash
        or not verify_password(user.password_hash, payload.password)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return await _new_session(db, response, user)


@router.post("/wallet/nonce", response_model=WalletNonceOut)
async def wallet_nonce(payload: WalletNonceIn, request: Request, db: Db) -> WalletNonceOut:
    settings = get_settings()
    if payload.chain_id != settings.arc_chain_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Wallet login must use Arc Testnet")
    domain = request.url.hostname or "localhost"
    nonce = random_token()[:20]
    message = siwe_message(
        domain=domain, address=payload.address, nonce=nonce, chain_id=payload.chain_id
    )
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    db.add(
        AuthNonce(
            nonce_hash=token_hash(nonce),
            address=payload.address.lower(),
            domain=domain,
            chain_id=payload.chain_id,
            message=message,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return WalletNonceOut(nonce=nonce, message=message, expires_at=expires_at)


@router.post("/wallet/verify", response_model=AuthOut)
async def wallet_verify(payload: WalletVerifyIn, response: Response, db: Db) -> AuthOut:
    nonce_row = await db.scalar(
        select(AuthNonce)
        .where(
            AuthNonce.address == payload.address.lower(),
            AuthNonce.message == payload.message,
            AuthNonce.consumed_at.is_(None),
        )
        .order_by(AuthNonce.expires_at.desc())
    )
    now = datetime.now(UTC)
    if not nonce_row or nonce_row.expires_at.replace(tzinfo=UTC) < now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Login request expired or already used")
    if recover_wallet(payload.message, payload.signature) != payload.address.lower():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wallet signature is invalid")
    nonce_row.consumed_at = now
    identity = await db.scalar(
        select(WalletIdentity).where(WalletIdentity.address == payload.address.lower())
    )
    if identity:
        user = await db.get(User, identity.user_id)
        assert user is not None
    else:
        user = User(display_name=f"Arc user {payload.address[:6]}")
        db.add(user)
        await db.flush()
        db.add(WalletIdentity(user_id=user.id, address=payload.address.lower()))
    return await _new_session(db, response, user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, user: CurrentUser, db: Db) -> None:
    del user, db
    response.delete_cookie("arcscrow_session", path="/")
    response.delete_cookie("arcscrow_refresh", path=f"{get_settings().api_prefix}/auth")
