"""alert rules delivery

Revision ID: 0004_alert_rules_delivery
Revises: 0003_fair_value_explanation_json
Create Date: 2026-04-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_alert_rules_delivery"
down_revision: str | None = "0003_fair_value_explanation_json"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_alert_rules_enabled", table_name="alert_rules")
    op.add_column("alert_rules", sa.Column("user_id", sa.String(length=120), nullable=False, server_default="default"))
    op.add_column("alert_rules", sa.Column("max_spread", sa.Float(), nullable=True))
    op.add_column("alert_rules", sa.Column("min_liquidity", sa.Float(), nullable=True))
    op.add_column("alert_rules", sa.Column("source", sa.String(length=40), nullable=True))
    op.add_column("alert_rules", sa.Column("delivery_channel", sa.String(length=40), nullable=False, server_default="discord"))
    op.add_column("alert_rules", sa.Column("delivery_target", sa.String(length=600), nullable=False, server_default=""))
    op.add_column("alert_rules", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE alert_rules SET is_active = enabled, delivery_target = COALESCE(destination, '')")
    op.alter_column("alert_rules", "user_id", server_default=None)
    op.alter_column("alert_rules", "delivery_channel", server_default=None)
    op.alter_column("alert_rules", "delivery_target", server_default=None)
    op.alter_column("alert_rules", "is_active", server_default=None)
    op.drop_constraint("alert_rules_user_model_id_fkey", "alert_rules", type_="foreignkey")
    op.drop_column("alert_rules", "user_model_id")
    op.drop_column("alert_rules", "min_confidence")
    op.drop_column("alert_rules", "enabled")
    op.drop_column("alert_rules", "destination")
    op.drop_column("alert_rules", "config")
    op.create_index("ix_alert_rules_is_active", "alert_rules", ["is_active"])
    op.create_index("ix_alert_rules_user_id", "alert_rules", ["user_id"])

    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("alert_rule_id", sa.String(length=36), nullable=False),
        sa.Column("market_id", sa.String(length=36), nullable=False),
        sa.Column("fair_value_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("delivery_channel", sa.String(length=40), nullable=False),
        sa.Column("delivery_target", sa.String(length=600), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["alert_rule_id"], ["alert_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fair_value_snapshot_id"], ["fair_value_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alert_deliveries_rule_market_sent",
        "alert_deliveries",
        ["alert_rule_id", "market_id", "sent_at"],
    )
    op.create_index("ix_alert_deliveries_snapshot", "alert_deliveries", ["fair_value_snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_alert_deliveries_snapshot", table_name="alert_deliveries")
    op.drop_index("ix_alert_deliveries_rule_market_sent", table_name="alert_deliveries")
    op.drop_table("alert_deliveries")
    op.drop_index("ix_alert_rules_user_id", table_name="alert_rules")
    op.drop_index("ix_alert_rules_is_active", table_name="alert_rules")
    op.add_column("alert_rules", sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("alert_rules", sa.Column("destination", sa.String(length=300), nullable=True))
    op.add_column("alert_rules", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("alert_rules", sa.Column("min_confidence", sa.Float(), nullable=False, server_default="0.55"))
    op.add_column("alert_rules", sa.Column("user_model_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "alert_rules_user_model_id_fkey",
        "alert_rules",
        "user_models",
        ["user_model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("UPDATE alert_rules SET enabled = is_active, destination = delivery_target")
    op.alter_column("alert_rules", "config", server_default=None)
    op.alter_column("alert_rules", "enabled", server_default=None)
    op.alter_column("alert_rules", "min_confidence", server_default=None)
    op.drop_column("alert_rules", "is_active")
    op.drop_column("alert_rules", "delivery_target")
    op.drop_column("alert_rules", "delivery_channel")
    op.drop_column("alert_rules", "source")
    op.drop_column("alert_rules", "min_liquidity")
    op.drop_column("alert_rules", "max_spread")
    op.drop_column("alert_rules", "user_id")
    op.create_index("ix_alert_rules_enabled", "alert_rules", ["enabled"])
