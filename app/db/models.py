import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class PlatformRole(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


class DealRole(str, enum.Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    CONTRIBUTOR = "CONTRIBUTOR"
    OBSERVER = "OBSERVER"
    APPROVER = "APPROVER"
    DEAL_ADMIN = "DEAL_ADMIN"
    ORGANISATION_REPRESENTATIVE = "ORGANISATION_REPRESENTATIVE"


class DealStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    NEGOTIATING = "NEGOTIATING"
    AWAITING_PARTIES = "AWAITING_PARTIES"
    AWAITING_SIGNATURES = "AWAITING_SIGNATURES"
    AWAITING_FUNDING = "AWAITING_FUNDING"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    READY_TO_START = "READY_TO_START"
    ACTIVE = "ACTIVE"
    MILESTONE_REVIEW = "MILESTONE_REVIEW"
    DISPUTED = "DISPUTED"
    COMPLETED = "COMPLETED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    ARCHIVED = "ARCHIVED"


class MilestoneStatus(str, enum.Enum):
    PENDING = "PENDING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    VERIFYING = "VERIFYING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISPUTED = "DISPUTED"
    RELEASE_QUEUED = "RELEASE_QUEUED"
    RELEASED = "RELEASED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str | None] = mapped_column(Text)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[PlatformRole] = mapped_column(Enum(PlatformRole), default=PlatformRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WalletIdentity(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "wallet_identities"
    __table_args__ = (UniqueConstraint("chain_namespace", "address"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chain_namespace: Mapped[str] = mapped_column(String(32), default="eip155")
    address: Mapped[str] = mapped_column(String(42), index=True)
    wallet_type: Mapped[str] = mapped_column(String(32), default="external")
    provider_reference: Mapped[str | None] = mapped_column(String(255))


class AuthNonce(Base, UUIDMixin):
    __tablename__ = "auth_nonces"
    nonce_hash: Mapped[str] = mapped_column(String(64), unique=True)
    address: Mapped[str] = mapped_column(String(42), index=True)
    domain: Mapped[str] = mapped_column(String(255))
    chain_id: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sessions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Organisation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organisations"
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class OrganisationMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organisation_members"
    __table_args__ = (UniqueConstraint("organisation_id", "user_id"),)
    organisation_id: Mapped[UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32))


class Deal(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "deals"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="total_amount_non_negative"),
        CheckConstraint(
            "funding_threshold_bps > 0 AND funding_threshold_bps <= 10000",
            name="funding_threshold_valid",
        ),
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    deal_type: Mapped[str] = mapped_column(String(64), default="MILESTONE_SERVICE")
    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus), default=DealStatus.DRAFT, index=True
    )
    organisation_id: Mapped[UUID | None] = mapped_column(ForeignKey("organisations.id"))
    creator_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    chain_id: Mapped[int] = mapped_column(Integer, default=5_042_002)
    token_address: Mapped[str] = mapped_column(String(42))
    token_symbol: Mapped[str] = mapped_column(String(16), default="USDC")
    token_decimals: Mapped[int] = mapped_column(Integer, default=6)
    total_amount: Mapped[int] = mapped_column(BigInteger)
    funded_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    released_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    disputed_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    refunded_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    funding_threshold_bps: Mapped[int] = mapped_column(Integer, default=5_000)
    onchain_deal_id: Mapped[str | None] = mapped_column(String(66), unique=True)
    registration_transaction_hash: Mapped[str | None] = mapped_column(String(66), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parties: Mapped[list["DealParty"]] = relationship(
        back_populates="deal", cascade="all, delete-orphan"
    )
    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="deal", cascade="all, delete-orphan"
    )


class DealParty(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "deal_parties"
    __table_args__ = (UniqueConstraint("deal_id", "user_id", "role"),)
    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[DealRole] = mapped_column(Enum(DealRole))
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    wallet_address: Mapped[str | None] = mapped_column(String(42), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acceptance_transaction_hash: Mapped[str | None] = mapped_column(String(66))
    deal: Mapped[Deal] = relationship(back_populates="parties")


class DealInvitation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "deal_invitations"
    __table_args__ = (UniqueConstraint("deal_id", "email", "role"),)
    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    invited_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    email: Mapped[str] = mapped_column(String(320), index=True)
    wallet_address: Mapped[str | None] = mapped_column(String(42))
    role: Mapped[DealRole] = mapped_column(Enum(DealRole))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgreementVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "agreement_versions"
    __table_args__ = (UniqueConstraint("deal_id", "version"),)
    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    structured_terms: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    pdf_storage_key: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class Milestone(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "milestones"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("released_amount >= 0", name="released_non_negative"),
    )
    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[int] = mapped_column(BigInteger)
    released_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[MilestoneStatus] = mapped_column(
        Enum(MilestoneStatus), default=MilestoneStatus.PENDING
    )
    rejection_limit: Mapped[int] = mapped_column(Integer, default=3)
    rejection_count: Mapped[int] = mapped_column(Integer, default=0)
    acceptance_criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_note: Mapped[str | None] = mapped_column(Text)
    submission_hash: Mapped[str | None] = mapped_column(String(66))
    submission_transaction_hash: Mapped[str | None] = mapped_column(String(66))
    approval_transaction_hash: Mapped[str | None] = mapped_column(String(66))
    release_transaction_hash: Mapped[str | None] = mapped_column(String(66))
    deal: Mapped[Deal] = relationship(back_populates="milestones")


class DealMessage(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "deal_messages"
    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("deal_messages.id"))
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageRevision(Base, UUIDMixin):
    __tablename__ = "message_revisions"
    __table_args__ = (UniqueConstraint("message_id", "revision"),)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("deal_messages.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvidenceItem(Base, UUIDMixin):
    __tablename__ = "evidence_items"
    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    milestone_id: Mapped[UUID | None] = mapped_column(ForeignKey("milestones.id"))
    type: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    source_entity_type: Mapped[str] = mapped_column(String(64))
    source_entity_id: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str | None] = mapped_column(String(512))
    content_hash: Mapped[str] = mapped_column(String(64))
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    anchored_onchain: Mapped[bool] = mapped_column(Boolean, default=False)
    anchor_transaction_hash: Mapped[str | None] = mapped_column(String(66))


class Dispute(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "disputes"
    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deals.id"), index=True)
    milestone_id: Mapped[UUID] = mapped_column(ForeignKey("milestones.id"), index=True)
    opened_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    requested_outcome: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="EVIDENCE_WINDOW")
    ruling: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class Notification(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "notifications"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    deep_link: Mapped[str | None] = mapped_column(String(512))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BlockchainEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "blockchain_events"
    __table_args__ = (UniqueConstraint("chain_id", "transaction_hash", "log_index"),)
    chain_id: Mapped[int] = mapped_column(Integer)
    contract_address: Mapped[str] = mapped_column(String(42))
    transaction_hash: Mapped[str] = mapped_column(String(66))
    block_number: Mapped[int] = mapped_column(BigInteger)
    block_hash: Mapped[str] = mapped_column(String(66))
    log_index: Mapped[int] = mapped_column(Integer)
    event_name: Mapped[str] = mapped_column(String(100))
    decoded_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="CONFIRMED")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Base, UUIDMixin):
    __tablename__ = "outbox_events"
    aggregate_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
