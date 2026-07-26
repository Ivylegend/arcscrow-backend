from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.db.models import DealRole, DealStatus, MilestoneStatus, PlatformRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str | None
    display_name: str
    email_verified: bool
    role: PlatformRole


class RegisterIn(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class AuthOut(BaseModel):
    user: UserOut
    csrf_token: str


class WalletNonceIn(BaseModel):
    address: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")
    chain_id: int = 5_042_002


class WalletNonceOut(BaseModel):
    nonce: str
    message: str
    expires_at: datetime


class WalletVerifyIn(BaseModel):
    address: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")
    message: str
    signature: str


class WalletLinkIn(WalletVerifyIn):
    pass


class MilestoneCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2, max_length=5000)
    amount: int = Field(gt=0)
    acceptance_criteria: list[dict[str, object]] = Field(min_length=1)
    rejection_limit: int = Field(default=3, ge=1, le=10)
    due_at: datetime | None = None


class DealCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=10_000)
    deal_type: str = "MILESTONE_SERVICE"
    total_amount: int = Field(gt=0)
    token_address: str = "0x3600000000000000000000000000000000000000"
    token_symbol: str = "USDC"
    token_decimals: int = Field(default=6, ge=0, le=18)
    funding_threshold_bps: int = Field(default=5_000, gt=0, le=10_000)
    buyer_wallet_address: str | None = Field(
        default=None, pattern=r"^0x[a-fA-F0-9]{40}$"
    )
    seller_email: EmailStr | None = None
    seller_wallet_address: str | None = Field(
        default=None, pattern=r"^0x[a-fA-F0-9]{40}$"
    )
    milestones: list[MilestoneCreate] = Field(min_length=1, max_length=50)

    @field_validator("milestones")
    @classmethod
    def milestone_positions(cls, value: list[MilestoneCreate]) -> list[MilestoneCreate]:
        if any(not item.acceptance_criteria for item in value):
            raise ValueError("Every milestone requires acceptance criteria")
        return value


class MilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    position: int
    title: str
    description: str
    amount: int
    released_amount: int
    status: MilestoneStatus
    rejection_limit: int
    rejection_count: int
    acceptance_criteria: list[dict[str, object]]
    due_at: datetime | None
    submission_note: str | None
    submission_hash: str | None
    submission_transaction_hash: str | None
    approval_transaction_hash: str | None
    release_transaction_hash: str | None


class PartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    role: DealRole
    permissions: dict[str, object]
    wallet_address: str | None
    accepted_at: datetime | None
    acceptance_transaction_hash: str | None


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    description: str
    deal_type: str
    status: DealStatus
    chain_id: int
    token_address: str
    token_symbol: str
    token_decimals: int
    total_amount: int
    funded_amount: int
    released_amount: int
    disputed_amount: int
    refunded_amount: int
    funding_threshold_bps: int
    onchain_deal_id: str | None
    registration_transaction_hash: str | None
    version: int
    parties: list[PartyOut] = []
    milestones: list[MilestoneOut] = []


class TransitionIn(BaseModel):
    status: DealStatus
    expected_version: int = Field(ge=1)


class FundingIn(BaseModel):
    amount: int = Field(gt=0)
    transaction_hash: str | None = Field(default=None, pattern=r"^0x[a-fA-F0-9]{64}$")
    simulated: bool = False


class InvitationCreate(BaseModel):
    email: EmailStr
    wallet_address: str | None = Field(default=None, pattern=r"^0x[a-fA-F0-9]{40}$")
    role: DealRole = DealRole.SELLER


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    deal_id: UUID
    email: str
    wallet_address: str | None
    role: DealRole
    status: str
    expires_at: datetime
    accept_token: str | None = None


class InvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    wallet_address: str | None = Field(default=None, pattern=r"^0x[a-fA-F0-9]{40}$")


class InvitationAcceptById(BaseModel):
    wallet_address: str | None = Field(default=None, pattern=r"^0x[a-fA-F0-9]{40}$")


class AgreementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int
    structured_terms: dict[str, object]
    content_hash: str
    created_by: UUID
    created_at: datetime


class AgreementAcceptIn(BaseModel):
    transaction_hash: str | None = Field(default=None, pattern=r"^0x[a-fA-F0-9]{64}$")


class OnchainPrepareOut(BaseModel):
    deal_id: str
    agreement_hash: str
    token: str
    funding_required: int
    funding_threshold_bps: int
    parties: list[str]
    roles: list[int]
    allocations: list[int]
    recipients: list[str]


class TransactionIn(BaseModel):
    transaction_hash: str = Field(pattern=r"^0x[a-fA-F0-9]{64}$")


class MilestoneSubmitIn(TransactionIn):
    note: str = Field(min_length=3, max_length=10_000)
    evidence_hash: str = Field(pattern=r"^0x[a-fA-F0-9]{64}$")


class DisputeCreateIn(TransactionIn):
    reason: str = Field(min_length=5, max_length=10_000)
    requested_outcome: str = Field(min_length=2, max_length=64)
    evidence_hash: str = Field(pattern=r"^0x[a-fA-F0-9]{64}$")


class DisputeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    deal_id: UUID
    milestone_id: UUID
    opened_by: UUID
    reason: str
    requested_outcome: str
    status: str
    ruling: dict[str, object] | None
    created_at: datetime


class BlockchainEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    transaction_hash: str
    block_number: int
    event_name: str
    decoded_data: dict[str, object]
    status: str
    created_at: datetime


class DealSuggestionIn(BaseModel):
    prompt: str = Field(min_length=20, max_length=10_000)
    total_amount: int | None = Field(default=None, gt=0)


class SuggestedMilestone(BaseModel):
    title: str
    description: str
    percentage: int = Field(gt=0, le=100)
    acceptance_criteria: list[str]


class DealSuggestionOut(BaseModel):
    title: str
    description: str
    suggested_total_amount: int | None = Field(default=None, gt=0)
    milestones: list[SuggestedMilestone] = Field(min_length=1, max_length=10)
    assumptions: list[str]


class WalletIdentityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    address: str
    chain_namespace: str
    wallet_type: str


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: str
    title: str
    body: str
    deep_link: str | None
    read_at: datetime | None
    created_at: datetime


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)


class OrganisationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=80)


class OrganisationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    owner_id: UUID
    created_at: datetime


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    parent_id: UUID | None = None


class MessageOut(BaseModel):
    id: UUID
    author_id: UUID
    content: str
    created_at: datetime


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    type: str
    actor_id: UUID | None
    source_entity_type: str
    source_entity_id: str
    content_hash: str
    previous_hash: str | None
    metadata_json: dict[str, object]
    occurred_at: datetime
    anchored_onchain: bool
