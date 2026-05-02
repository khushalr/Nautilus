from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MarketOut(BaseModel):
    id: str
    source: str
    external_id: str
    event_name: str
    league: str | None = None
    market_type: str
    selection: str
    normalized_event_key: str
    start_time: datetime | None = None
    status: str
    market_url: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class PredictionMarketSnapshotOut(BaseModel):
    id: str
    market_id: str
    source: str
    bid_probability: float | None = None
    ask_probability: float | None = None
    last_price: float | None = None
    midpoint_probability: float
    spread: float | None = None
    liquidity: float | None = None
    volume: float | None = None
    observed_at: datetime

    model_config = {"from_attributes": True}


class SportsbookOddsSnapshotOut(BaseModel):
    id: str
    bookmaker: str
    market_type: str
    selection: str
    american_odds: int | None = None
    decimal_odds: float | None = None
    implied_probability: float
    observed_at: datetime

    model_config = {"from_attributes": True}


class FairValueSnapshotOut(BaseModel):
    id: str
    market_id: str
    fair_probability: float
    market_probability: float
    gross_edge: float
    net_edge: float
    spread: float | None = None
    liquidity: float | None = None
    confidence_score: float
    sportsbook_consensus: dict[str, Any]
    assumptions: dict[str, Any]
    explanation_json: dict[str, Any] = Field(default_factory=dict)
    explanation: str
    observed_at: datetime

    model_config = {"from_attributes": True}


class MarketDetailOut(BaseModel):
    market: MarketOut
    latest_fair_value: FairValueSnapshotOut | None = None
    prediction_snapshots: list[PredictionMarketSnapshotOut]
    fair_value_history: list[FairValueSnapshotOut]
    sportsbook_odds: list[SportsbookOddsSnapshotOut]


class OpportunityOut(BaseModel):
    market: MarketOut
    fair_value: FairValueSnapshotOut


class OpportunityScannerOut(BaseModel):
    market_id: str
    title: str
    source: str
    external_id: str
    league: str | None = None
    market_type: str
    outcome: str | None = None
    display_outcome: str | None = None
    start_time: datetime | None = None
    status: str
    market_url: str | None = None
    market_probability: float
    fair_probability: float
    gross_edge: float
    net_edge: float
    spread: float | None = None
    liquidity: float | None = None
    confidence_score: float
    matched_sportsbook_category: str | None = None
    matched_selection: str | None = None
    match_confidence: float | None = None
    sportsbooks_used: list[str] = Field(default_factory=list)
    last_updated: datetime
    assumptions: dict[str, Any] | None = None
    explanation_json: dict[str, Any] | None = None
    market_extra: dict[str, Any] | None = None


class OpportunityHistoryRow(BaseModel):
    timestamp: datetime
    market_probability: float
    fair_probability: float
    gross_edge: float
    net_edge: float
    confidence_score: float


class SignalPerformanceBucket(BaseModel):
    key: str
    total_signals: int
    evaluated_signals: int
    simulated_long_yes_signals: int = 0
    evaluated_long_yes_signals: int = 0
    tracked_negative_edge_signals: int = 0
    simulated_negative_edge_signals: int = 0
    evaluated_negative_edge_signals: int = 0
    unevaluated_signals: int = 0
    suspicious_invalid_signals: int = 0
    skipped_invalid_signals: int = 0
    average_entry_edge: float | None = None
    average_paper_pnl_per_contract: float | None = None
    average_return_on_stake: float | None = None
    yes_side_average_paper_pnl_per_contract: float | None = None
    yes_side_average_return_on_stake: float | None = None
    no_side_average_paper_pnl_per_contract: float | None = None
    no_side_average_return_on_stake: float | None = None
    edge_close_rate: float | None = None
    directional_accuracy: float | None = None
    market_driven_close_rate: float | None = None
    fair_value_driven_close_rate: float | None = None
    both_moved_close_rate: float | None = None
    edge_widened_rate: float | None = None
    no_meaningful_change_rate: float | None = None
    average_market_yes_change: float | None = None
    average_sportsbook_fair_change: float | None = None
    average_edge_change: float | None = None
    average_absolute_edge_change: float | None = None
    contains_unadjusted_liquidity: bool = False


class SignalPerformanceSummary(BaseModel):
    total_signals: int
    evaluated_signals: int
    simulated_long_yes_signals: int = 0
    evaluated_long_yes_signals: int = 0
    tracked_negative_edge_signals: int = 0
    simulated_negative_edge_signals: int = 0
    evaluated_negative_edge_signals: int = 0
    unevaluated_signals: int = 0
    suspicious_invalid_signals: int = 0
    skipped_invalid_signals: int = 0
    average_entry_edge: float | None = None
    average_paper_pnl_per_contract: float | None = None
    average_return_on_stake: float | None = None
    yes_side_average_paper_pnl_per_contract: float | None = None
    yes_side_average_return_on_stake: float | None = None
    no_side_average_paper_pnl_per_contract: float | None = None
    no_side_average_return_on_stake: float | None = None
    edge_close_rate: float | None = None
    directional_accuracy: float | None = None
    market_driven_close_rate: float | None = None
    fair_value_driven_close_rate: float | None = None
    both_moved_close_rate: float | None = None
    edge_widened_rate: float | None = None
    no_meaningful_change_rate: float | None = None
    average_market_yes_change: float | None = None
    average_sportsbook_fair_change: float | None = None
    average_edge_change: float | None = None
    average_absolute_edge_change: float | None = None
    contains_unadjusted_liquidity: bool = False
    by_horizon: list[SignalPerformanceBucket] = Field(default_factory=list)
    by_confidence_bucket: list[SignalPerformanceBucket] = Field(default_factory=list)
    by_market_type: list[SignalPerformanceBucket] = Field(default_factory=list)
    by_league: list[SignalPerformanceBucket] = Field(default_factory=list)


class SignalPerformanceRow(BaseModel):
    signal_id: str
    market_id: str
    timestamp: datetime
    title: str
    display_outcome: str | None = None
    market_type: str
    league: str | None = None
    direction: str
    signal_direction: str | None = None
    paper_side: str | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    entry_market_yes_probability: float
    entry_sportsbook_fair_probability: float
    entry_net_edge: float | None = None
    horizon: str
    exit_market_yes_probability: float | None = None
    exit_sportsbook_fair_probability: float | None = None
    exit_net_edge: float | None = None
    market_yes_change: float | None = None
    sportsbook_fair_change: float | None = None
    edge_change: float | None = None
    absolute_edge_change: float | None = None
    closure_reason: str | None = None
    paper_pnl_per_contract: float | None = None
    return_on_stake: float | None = None
    did_edge_close: bool | None = None
    moved_expected_direction: bool | None = None
    confidence_score: float
    skip_reason: str | None = None
    evaluation_status: str
    signal_category: str
    raw_outcome_side: str | None = None
    raw_historical_price: float | None = None
    derived_market_yes_probability: float | None = None
    suspicion_reason: str | None = None
    liquidity_status: str | None = None
    liquidity_adjusted: bool | None = None


class UserModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    config: dict[str, Any] = Field(default_factory=dict)


class UserModelOut(UserModelCreate):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    user_id: str = Field(default="default", min_length=1, max_length=120)
    min_net_edge: float = 0.03
    max_spread: float | None = None
    min_liquidity: float | None = None
    league: str | None = None
    source: str | None = None
    delivery_channel: str = "discord"
    delivery_target: str = Field(min_length=1, max_length=600)
    is_active: bool = True


class AlertRuleUpdate(BaseModel):
    user_id: str | None = Field(default=None, min_length=1, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    min_net_edge: float | None = None
    max_spread: float | None = None
    min_liquidity: float | None = None
    league: str | None = None
    source: str | None = None
    delivery_channel: str | None = None
    delivery_target: str | None = Field(default=None, min_length=1, max_length=600)
    is_active: bool | None = None


class AlertRuleOut(AlertRuleCreate):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
