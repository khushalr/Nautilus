"""collector payload jsonb and last prices

Revision ID: 0002_collector_payload_jsonb
Revises: 0001_initial_schema
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_collector_payload_jsonb"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSON_COLUMNS = (
    ("markets", "extra"),
    ("sportsbook_events", "extra"),
    ("user_models", "config"),
    ("alert_rules", "config"),
    ("fair_value_snapshots", "sportsbook_consensus"),
    ("fair_value_snapshots", "assumptions"),
    ("prediction_market_snapshots", "raw_payload"),
    ("sportsbook_odds_snapshots", "raw_payload"),
)


def upgrade() -> None:
    op.add_column("prediction_market_snapshots", sa.Column("last_price", sa.Float(), nullable=True))
    for table_name, column_name in JSON_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.JSON(),
            type_=postgresql.JSONB(),
            postgresql_using=f"{column_name}::jsonb",
            existing_nullable=False,
        )


def downgrade() -> None:
    for table_name, column_name in reversed(JSON_COLUMNS):
        op.alter_column(
            table_name,
            column_name,
            existing_type=postgresql.JSONB(),
            type_=sa.JSON(),
            postgresql_using=f"{column_name}::json",
            existing_nullable=False,
        )
    op.drop_column("prediction_market_snapshots", "last_price")
