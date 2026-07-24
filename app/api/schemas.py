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


class PartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    role: DealRole
    permissions: dict[str, object]


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


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    parent_id: UUID | None = None


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
