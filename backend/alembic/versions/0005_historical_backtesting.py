"""historical backtesting tables

Revision ID: 0005_historical_backtesting
Revises: 0004_alert_rules_delivery
Create Date: 2026-04-30 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_historical_backtesting"
down_revision = "0004_alert_rules_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_prediction_market_price_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("market_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("token_id", sa.String(length=220), nullable=True),
        sa.Column("raw_selection", sa.String(length=180), nullable=False),
        sa.Column("display_outcome", sa.String(length=180), nullable=True),
        sa.Column("raw_price", sa.Float(), nullable=False),
        sa.Column("market_yes_price", sa.Float(), nullable=False),
        sa.Column("orientation", sa.String(length=80), nullable=False),
        sa.Column("liquidity", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("market_id", "token_id", "timestamp", name="uq_historical_prediction_market_token_time"),
    )
    op.create_index(
        "ix_historical_prediction_market_time",
        "historical_prediction_market_price_snapshots",
        ["market_id", "timestamp"],
    )
    op.create_index(
        "ix_historical_prediction_token_time",
        "historical_prediction_market_price_snapshots",
        ["token_id", "timestamp"],
    )

    op.create_table(
        "historical_sportsbook_odds_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("provider_event_id", sa.String(length=180), nullable=False),
        sa.Column("event_name", sa.String(length=300), nullable=False),
        sa.Column("league", sa.String(length=80), nullable=True),
        sa.Column("home_team", sa.String(length=180), nullable=True),
        sa.Column("away_team", sa.String(length=180), nullable=True),
        sa.Column("normalized_event_key", sa.String(length=260), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bookmaker", sa.String(length=120), nullable=False),
        sa.Column("market_type", sa.String(length=80), nullable=False),
        sa.Column("selection", sa.String(length=180), nullable=False),
        sa.Column("american_odds", sa.Integer(), nullable=True),
        sa.Column("decimal_odds", sa.Float(), nullable=True),
        sa.Column("implied_probability", sa.Float(), nullable=False),
        sa.Column("snapshot_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_historical_sportsbook_snapshot_market",
        "historical_sportsbook_odds_snapshots",
        ["snapshot_timestamp", "market_type"],
    )
    op.create_index(
        "ix_historical_sportsbook_event_selection",
        "historical_sportsbook_odds_snapshots",
        ["provider_event_id", "selection", "snapshot_timestamp"],
    )

    op.create_table(
        "paper_trade_signals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("market_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("market_type", sa.String(length=80), nullable=False),
        sa.Column("league", sa.String(length=80), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("display_outcome", sa.String(length=180), nullable=True),
        sa.Column("direction", sa.String(length=80), nullable=False),
        sa.Column("entry_market_yes_probability", sa.Float(), nullable=False),
        sa.Column("entry_sportsbook_fair_probability", sa.Float(), nullable=False),
        sa.Column("entry_net_edge", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=False),
        sa.Column("liquidity", sa.Float(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_trade_signals_market_timestamp", "paper_trade_signals", ["market_id", "timestamp"])
    op.create_index("ix_paper_trade_signals_direction", "paper_trade_signals", ["direction"])

    op.create_table(
        "signal_backtest_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("signal_id", sa.String(length=36), nullable=False),
        sa.Column("market_id", sa.String(length=36), nullable=False),
        sa.Column("horizon", sa.String(length=20), nullable=False),
        sa.Column("exit_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_market_yes_probability", sa.Float(), nullable=True),
        sa.Column("exit_sportsbook_fair_probability", sa.Float(), nullable=True),
        sa.Column("exit_net_edge", sa.Float(), nullable=True),
        sa.Column("paper_pnl_per_contract", sa.Float(), nullable=True),
        sa.Column("return_on_stake", sa.Float(), nullable=True),
        sa.Column("edge_change", sa.Float(), nullable=True),
        sa.Column("did_edge_close", sa.Boolean(), nullable=True),
        sa.Column("moved_expected_direction", sa.Boolean(), nullable=True),
        sa.Column("skip_reason", sa.String(length=120), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["signal_id"], ["paper_trade_signals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signal_backtest_results_horizon", "signal_backtest_results", ["horizon"])
    op.create_index("ix_signal_backtest_results_market_horizon", "signal_backtest_results", ["market_id", "horizon"])


def downgrade() -> None:
    op.drop_index("ix_signal_backtest_results_market_horizon", table_name="signal_backtest_results")
    op.drop_index("ix_signal_backtest_results_horizon", table_name="signal_backtest_results")
    op.drop_table("signal_backtest_results")
    op.drop_index("ix_paper_trade_signals_direction", table_name="paper_trade_signals")
    op.drop_index("ix_paper_trade_signals_market_timestamp", table_name="paper_trade_signals")
    op.drop_table("paper_trade_signals")
    op.drop_index("ix_historical_sportsbook_event_selection", table_name="historical_sportsbook_odds_snapshots")
    op.drop_index("ix_historical_sportsbook_snapshot_market", table_name="historical_sportsbook_odds_snapshots")
    op.drop_table("historical_sportsbook_odds_snapshots")
    op.drop_index("ix_historical_prediction_token_time", table_name="historical_prediction_market_price_snapshots")
    op.drop_index("ix_historical_prediction_market_time", table_name="historical_prediction_market_price_snapshots")
    op.drop_table("historical_prediction_market_price_snapshots")
