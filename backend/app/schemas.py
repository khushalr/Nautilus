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
