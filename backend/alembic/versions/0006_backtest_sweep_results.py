"""backtest sweep results

Revision ID: 0006_backtest_sweep_results
Revises: 0005_historical_backtesting
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_backtest_sweep_results"
down_revision = "0005_historical_backtesting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_sweep_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("min_abs_edge", sa.Float(), nullable=False),
        sa.Column("min_confidence_score", sa.Float(), nullable=False),
        sa.Column("min_match_confidence", sa.Float(), nullable=False),
        sa.Column("simulate_negative_edge", sa.Boolean(), nullable=False),
        sa.Column("signals_created", sa.Integer(), nullable=False),
        sa.Column("evaluated_yes_side", sa.Integer(), nullable=False),
        sa.Column("evaluated_no_side", sa.Integer(), nullable=False),
        sa.Column("directional_accuracy", sa.Float(), nullable=True),
        sa.Column("average_paper_pnl_per_contract", sa.Float(), nullable=True),
        sa.Column("average_return_on_stake", sa.Float(), nullable=True),
        sa.Column("edge_close_rate", sa.Float(), nullable=True),
        sa.Column("market_driven_close_rate", sa.Float(), nullable=True),
        sa.Column("fair_value_driven_close_rate", sa.Float(), nullable=True),
        sa.Column("suspicious_invalid_count", sa.Integer(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtest_sweep_results_run_created", "backtest_sweep_results", ["run_id", "created_at"])
    op.create_index("ix_backtest_sweep_results_created", "backtest_sweep_results", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_backtest_sweep_results_created", table_name="backtest_sweep_results")
    op.drop_index("ix_backtest_sweep_results_run_created", table_name="backtest_sweep_results")
    op.drop_table("backtest_sweep_results")
