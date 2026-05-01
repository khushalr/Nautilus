from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


JSON_DICT = JSON().with_variant(JSONB(), "postgresql")


def new_uuid() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Market(TimestampMixin, Base):
    __tablename__ = "markets"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_markets_source_external_id"),
        Index("ix_markets_normalized_event_key", "normalized_event_key"),
        Index("ix_markets_start_time", "start_time"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_name: Mapped[str] = mapped_column(String(300), nullable=False)
    league: Mapped[str | None] = mapped_column(String(80))
    market_type: Mapped[str] = mapped_column(String(80), default="moneyline", nullable=False)
    selection: Mapped[str] = mapped_column(String(180), nullable=False)
    normalized_event_key: Mapped[str] = mapped_column(String(260), nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)
    market_url: Mapped[str | None] = mapped_column(String(600))
    extra: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)

    prediction_snapshots: Mapped[list[PredictionMarketSnapshot]] = relationship(
        back_populates="market",
        cascade="all, delete-orphan",
    )
    fair_value_snapshots: Mapped[list[FairValueSnapshot]] = relationship(
        back_populates="market",
        cascade="all, delete-orphan",
    )


class PredictionMarketSnapshot(Base):
    __tablename__ = "prediction_market_snapshots"
    __table_args__ = (
        Index("ix_prediction_snapshots_market_observed", "market_id", "observed_at"),
        Index("ix_prediction_snapshots_source_observed", "source", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    bid_probability: Mapped[float | None] = mapped_column(Float)
    ask_probability: Mapped[float | None] = mapped_column(Float)
    last_price: Mapped[float | None] = mapped_column(Float)
    midpoint_probability: Mapped[float] = mapped_column(Float, nullable=False)
    spread: Mapped[float | None] = mapped_column(Float)
    liquidity: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    raw_payload: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    market: Mapped[Market] = relationship(back_populates="prediction_snapshots")


class HistoricalPredictionMarketPriceSnapshot(Base):
    __tablename__ = "historical_prediction_market_price_snapshots"
    __table_args__ = (
        Index("ix_historical_prediction_market_time", "market_id", "timestamp"),
        Index("ix_historical_prediction_token_time", "token_id", "timestamp"),
        UniqueConstraint("market_id", "token_id", "timestamp", name="uq_historical_prediction_market_token_time"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    token_id: Mapped[str | None] = mapped_column(String(220))
    raw_selection: Mapped[str] = mapped_column(String(180), nullable=False)
    display_outcome: Mapped[str | None] = mapped_column(String(180))
    raw_price: Mapped[float] = mapped_column(Float, nullable=False)
    market_yes_price: Mapped[float] = mapped_column(Float, nullable=False)
    orientation: Mapped[str] = mapped_column(String(80), nullable=False)
    liquidity: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    market: Mapped[Market] = relationship()


class SportsbookEvent(TimestampMixin, Base):
    __tablename__ = "sportsbook_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_sportsbook_events_provider_event_id"),
        Index("ix_sportsbook_events_normalized_event_key", "normalized_event_key"),
        Index("ix_sportsbook_events_start_time", "start_time"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    provider: Mapped[str] = mapped_column(String(60), default="odds_api", nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(180), nullable=False)
    event_name: Mapped[str] = mapped_column(String(300), nullable=False)
    league: Mapped[str | None] = mapped_column(String(80))
    home_team: Mapped[str | None] = mapped_column(String(180))
    away_team: Mapped[str | None] = mapped_column(String(180))
    normalized_event_key: Mapped[str] = mapped_column(String(260), nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)

    odds_snapshots: Mapped[list[SportsbookOddsSnapshot]] = relationship(
        back_populates="event",
        cascade="all, delete-orphan",
    )


class SportsbookOddsSnapshot(Base):
    __tablename__ = "sportsbook_odds_snapshots"
    __table_args__ = (
        Index("ix_sportsbook_odds_event_observed", "event_id", "observed_at"),
        Index("ix_sportsbook_odds_bookmaker_observed", "bookmaker", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    event_id: Mapped[str] = mapped_column(ForeignKey("sportsbook_events.id", ondelete="CASCADE"), nullable=False)
    bookmaker: Mapped[str] = mapped_column(String(120), nullable=False)
    market_type: Mapped[str] = mapped_column(String(80), default="moneyline", nullable=False)
    selection: Mapped[str] = mapped_column(String(180), nullable=False)
    american_odds: Mapped[int | None] = mapped_column(Integer)
    decimal_odds: Mapped[float | None] = mapped_column(Float)
    implied_probability: Mapped[float] = mapped_column(Float, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    event: Mapped[SportsbookEvent] = relationship(back_populates="odds_snapshots")


class HistoricalSportsbookOddsSnapshot(Base):
    __tablename__ = "historical_sportsbook_odds_snapshots"
    __table_args__ = (
        Index("ix_historical_sportsbook_snapshot_market", "snapshot_timestamp", "market_type"),
        Index("ix_historical_sportsbook_event_selection", "provider_event_id", "selection", "snapshot_timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    provider: Mapped[str] = mapped_column(String(60), default="odds_api", nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(180), nullable=False)
    event_name: Mapped[str] = mapped_column(String(300), nullable=False)
    league: Mapped[str | None] = mapped_column(String(80))
    home_team: Mapped[str | None] = mapped_column(String(180))
    away_team: Mapped[str | None] = mapped_column(String(180))
    normalized_event_key: Mapped[str] = mapped_column(String(260), nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bookmaker: Mapped[str] = mapped_column(String(120), nullable=False)
    market_type: Mapped[str] = mapped_column(String(80), nullable=False)
    selection: Mapped[str] = mapped_column(String(180), nullable=False)
    american_odds: Mapped[int | None] = mapped_column(Integer)
    decimal_odds: Mapped[float | None] = mapped_column(Float)
    implied_probability: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class FairValueSnapshot(Base):
    __tablename__ = "fair_value_snapshots"
    __table_args__ = (
        Index("ix_fair_values_market_observed", "market_id", "observed_at"),
        Index("ix_fair_values_net_edge", "net_edge"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    fair_probability: Mapped[float] = mapped_column(Float, nullable=False)
    market_probability: Mapped[float] = mapped_column(Float, nullable=False)
    gross_edge: Mapped[float] = mapped_column(Float, nullable=False)
    net_edge: Mapped[float] = mapped_column(Float, nullable=False)
    spread: Mapped[float | None] = mapped_column(Float)
    liquidity: Mapped[float | None] = mapped_column(Float)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    sportsbook_consensus: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)
    assumptions: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)
    explanation_json: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    market: Mapped[Market] = relationship(back_populates="fair_value_snapshots")


class PaperTradeSignal(Base):
    __tablename__ = "paper_trade_signals"
    __table_args__ = (
        Index("ix_paper_trade_signals_market_timestamp", "market_id", "timestamp"),
        Index("ix_paper_trade_signals_direction", "direction"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    market_type: Mapped[str] = mapped_column(String(80), nullable=False)
    league: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    display_outcome: Mapped[str | None] = mapped_column(String(180))
    direction: Mapped[str] = mapped_column(String(80), nullable=False)
    entry_market_yes_probability: Mapped[float] = mapped_column(Float, nullable=False)
    entry_sportsbook_fair_probability: Mapped[float] = mapped_column(Float, nullable=False)
    entry_net_edge: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    liquidity: Mapped[float | None] = mapped_column(Float)
    raw_payload: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    market: Mapped[Market] = relationship()
    results: Mapped[list[SignalBacktestResult]] = relationship(
        back_populates="signal",
        cascade="all, delete-orphan",
    )


class SignalBacktestResult(Base):
    __tablename__ = "signal_backtest_results"
    __table_args__ = (
        Index("ix_signal_backtest_results_horizon", "horizon"),
        Index("ix_signal_backtest_results_market_horizon", "market_id", "horizon"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    signal_id: Mapped[str] = mapped_column(ForeignKey("paper_trade_signals.id", ondelete="CASCADE"), nullable=False)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    horizon: Mapped[str] = mapped_column(String(20), nullable=False)
    exit_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_market_yes_probability: Mapped[float | None] = mapped_column(Float)
    exit_sportsbook_fair_probability: Mapped[float | None] = mapped_column(Float)
    exit_net_edge: Mapped[float | None] = mapped_column(Float)
    paper_pnl_per_contract: Mapped[float | None] = mapped_column(Float)
    return_on_stake: Mapped[float | None] = mapped_column(Float)
    edge_change: Mapped[float | None] = mapped_column(Float)
    did_edge_close: Mapped[bool | None] = mapped_column(Boolean)
    moved_expected_direction: Mapped[bool | None] = mapped_column(Boolean)
    skip_reason: Mapped[str | None] = mapped_column(String(120))
    raw_payload: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    signal: Mapped[PaperTradeSignal] = relationship(back_populates="results")
    market: Mapped[Market] = relationship()


class UserModel(TimestampMixin, Base):
    __tablename__ = "user_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    config: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)


class AlertRule(TimestampMixin, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        Index("ix_alert_rules_is_active", "is_active"),
        Index("ix_alert_rules_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(120), default="default", nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    min_net_edge: Mapped[float] = mapped_column(Float, default=0.03, nullable=False)
    max_spread: Mapped[float | None] = mapped_column(Float)
    min_liquidity: Mapped[float | None] = mapped_column(Float)
    league: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str | None] = mapped_column(String(40))
    delivery_channel: Mapped[str] = mapped_column(String(40), default="discord", nullable=False)
    delivery_target: Mapped[str] = mapped_column(String(600), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    deliveries: Mapped[list[AlertDelivery]] = relationship(
        back_populates="alert_rule",
        cascade="all, delete-orphan",
    )


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    __table_args__ = (
        Index("ix_alert_deliveries_rule_market_sent", "alert_rule_id", "market_id", "sent_at"),
        Index("ix_alert_deliveries_snapshot", "fair_value_snapshot_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    alert_rule_id: Mapped[str] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id", ondelete="CASCADE"), nullable=False)
    fair_value_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("fair_value_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    delivery_channel: Mapped[str] = mapped_column(String(40), nullable=False)
    delivery_target: Mapped[str] = mapped_column(String(600), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="sent", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON_DICT, default=dict, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    alert_rule: Mapped[AlertRule] = relationship(back_populates="deliveries")
