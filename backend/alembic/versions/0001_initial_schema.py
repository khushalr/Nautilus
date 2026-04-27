"""initial nautilus schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "markets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("external_id", sa.String(length=160), nullable=False),
        sa.Column("event_name", sa.String(length=300), nullable=False),
        sa.Column("league", sa.String(length=80), nullable=True),
        sa.Column("market_type", sa.String(length=80), nullable=False),
        sa.Column("selection", sa.String(length=180), nullable=False),
        sa.Column("normalized_event_key", sa.String(length=260), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("market_url", sa.String(length=600), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_markets_source_external_id"),
    )
    op.create_index("ix_markets_normalized_event_key", "markets", ["normalized_event_key"])
    op.create_index("ix_markets_start_time", "markets", ["start_time"])

    op.create_table(
        "sportsbook_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("provider_event_id", sa.String(length=180), nullable=False),
        sa.Column("event_name", sa.String(length=300), nullable=False),
        sa.Column("league", sa.String(length=80), nullable=True),
        sa.Column("home_team", sa.String(length=180), nullable=True),
        sa.Column("away_team", sa.String(length=180), nullable=True),
        sa.Column("normalized_event_key", sa.String(length=260), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_sportsbook_events_provider_event_id"),
    )
    op.create_index("ix_sportsbook_events_normalized_event_key", "sportsbook_events", ["normalized_event_key"])
    op.create_index("ix_sportsbook_events_start_time", "sportsbook_events", ["start_time"])

    op.create_table(
        "user_models",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("user_model_id", sa.String(length=36), nullable=True),
        sa.Column("min_net_edge", sa.Float(), nullable=False),
        sa.Column("min_confidence", sa.Float(), nullable=False),
        sa.Column("league", sa.String(length=80), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("destination", sa.String(length=300), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_model_id"], ["user_models.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_rules_enabled", "alert_rules", ["enabled"])

    op.create_table(
        "fair_value_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("market_id", sa.String(length=36), nullable=False),
        sa.Column("fair_probability", sa.Float(), nullable=False),
        sa.Column("market_probability", sa.Float(), nullable=False),
        sa.Column("gross_edge", sa.Float(), nullable=False),
        sa.Column("net_edge", sa.Float(), nullable=False),
        sa.Column("spread", sa.Float(), nullable=True),
        sa.Column("liquidity", sa.Float(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("sportsbook_consensus", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fair_values_market_observed", "fair_value_snapshots", ["market_id", "observed_at"])
    op.create_index("ix_fair_values_net_edge", "fair_value_snapshots", ["net_edge"])

    op.create_table(
        "prediction_market_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("market_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("bid_probability", sa.Float(), nullable=True),
        sa.Column("ask_probability", sa.Float(), nullable=True),
        sa.Column("midpoint_probability", sa.Float(), nullable=False),
        sa.Column("spread", sa.Float(), nullable=True),
        sa.Column("liquidity", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prediction_snapshots_market_observed",
        "prediction_market_snapshots",
        ["market_id", "observed_at"],
    )
    op.create_index(
        "ix_prediction_snapshots_source_observed",
        "prediction_market_snapshots",
        ["source", "observed_at"],
    )

    op.create_table(
        "sportsbook_odds_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("bookmaker", sa.String(length=120), nullable=False),
        sa.Column("market_type", sa.String(length=80), nullable=False),
        sa.Column("selection", sa.String(length=180), nullable=False),
        sa.Column("american_odds", sa.Integer(), nullable=True),
        sa.Column("decimal_odds", sa.Float(), nullable=True),
        sa.Column("implied_probability", sa.Float(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["sportsbook_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sportsbook_odds_event_observed",
        "sportsbook_odds_snapshots",
        ["event_id", "observed_at"],
    )
    op.create_index(
        "ix_sportsbook_odds_bookmaker_observed",
        "sportsbook_odds_snapshots",
        ["bookmaker", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sportsbook_odds_bookmaker_observed", table_name="sportsbook_odds_snapshots")
    op.drop_index("ix_sportsbook_odds_event_observed", table_name="sportsbook_odds_snapshots")
    op.drop_table("sportsbook_odds_snapshots")
    op.drop_index("ix_prediction_snapshots_source_observed", table_name="prediction_market_snapshots")
    op.drop_index("ix_prediction_snapshots_market_observed", table_name="prediction_market_snapshots")
    op.drop_table("prediction_market_snapshots")
    op.drop_index("ix_fair_values_net_edge", table_name="fair_value_snapshots")
    op.drop_index("ix_fair_values_market_observed", table_name="fair_value_snapshots")
    op.drop_table("fair_value_snapshots")
    op.drop_index("ix_alert_rules_enabled", table_name="alert_rules")
    op.drop_table("alert_rules")
    op.drop_table("user_models")
    op.drop_index("ix_sportsbook_events_start_time", table_name="sportsbook_events")
    op.drop_index("ix_sportsbook_events_normalized_event_key", table_name="sportsbook_events")
    op.drop_table("sportsbook_events")
    op.drop_index("ix_markets_start_time", table_name="markets")
    op.drop_index("ix_markets_normalized_event_key", table_name="markets")
    op.drop_table("markets")
