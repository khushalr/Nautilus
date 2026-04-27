"""fair value explanation json

Revision ID: 0003_fair_value_explanation_json
Revises: 0002_collector_payload_jsonb
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_fair_value_explanation_json"
down_revision: str | None = "0002_collector_payload_jsonb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fair_value_snapshots",
        sa.Column(
            "explanation_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("fair_value_snapshots", "explanation_json", server_default=None)


def downgrade() -> None:
    op.drop_column("fair_value_snapshots", "explanation_json")
