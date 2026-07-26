"""complete deal workflow

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("registration_transaction_hash", sa.String(66)))
    op.create_unique_constraint(
        "uq_deals_registration_transaction_hash",
        "deals",
        ["registration_transaction_hash"],
    )
    op.add_column("deal_parties", sa.Column("wallet_address", sa.String(42)))
    op.add_column("deal_parties", sa.Column("accepted_at", sa.DateTime(timezone=True)))
    op.add_column(
        "deal_parties",
        sa.Column("acceptance_transaction_hash", sa.String(66)),
    )
    op.create_index("ix_deal_parties_wallet_address", "deal_parties", ["wallet_address"])
    op.add_column("milestones", sa.Column("submission_note", sa.Text()))
    op.add_column("milestones", sa.Column("submission_hash", sa.String(66)))
    op.add_column(
        "milestones",
        sa.Column("submission_transaction_hash", sa.String(66)),
    )
    op.add_column(
        "milestones",
        sa.Column("approval_transaction_hash", sa.String(66)),
    )
    op.add_column(
        "milestones",
        sa.Column("release_transaction_hash", sa.String(66)),
    )
    if not sa.inspect(op.get_bind()).has_table("deal_invitations"):
        op.create_table(
            "deal_invitations",
            sa.Column("deal_id", sa.Uuid(), nullable=False),
            sa.Column("invited_by", sa.Uuid(), nullable=False),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("wallet_address", sa.String(42)),
            sa.Column(
                "role",
                postgresql.ENUM(
                    "BUYER",
                    "SELLER",
                    "CONTRIBUTOR",
                    "OBSERVER",
                    "APPROVER",
                    "DEAL_ADMIN",
                    "ORGANISATION_REPRESENTATIVE",
                    name="dealrole",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_by", sa.Uuid()),
            sa.Column("accepted_at", sa.DateTime(timezone=True)),
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["invited_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["accepted_by"], ["users.id"]),
            sa.UniqueConstraint("deal_id", "email", "role"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index("ix_deal_invitations_deal_id", "deal_invitations", ["deal_id"])
        op.create_index("ix_deal_invitations_email", "deal_invitations", ["email"])
        op.create_index("ix_deal_invitations_status", "deal_invitations", ["status"])


def downgrade() -> None:
    op.drop_table("deal_invitations")
    op.drop_column("milestones", "release_transaction_hash")
    op.drop_column("milestones", "approval_transaction_hash")
    op.drop_column("milestones", "submission_transaction_hash")
    op.drop_column("milestones", "submission_hash")
    op.drop_column("milestones", "submission_note")
    op.drop_index("ix_deal_parties_wallet_address", table_name="deal_parties")
    op.drop_column("deal_parties", "acceptance_transaction_hash")
    op.drop_column("deal_parties", "accepted_at")
    op.drop_column("deal_parties", "wallet_address")
    op.drop_constraint("uq_deals_registration_transaction_hash", "deals", type_="unique")
    op.drop_column("deals", "registration_transaction_hash")
