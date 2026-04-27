from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PredictionMarketQuote:
    source: str
    external_id: str
    event_name: str
    league: str | None
    market_type: str
    selection: str
    normalized_event_key: str
    start_time: datetime | None
    bid_probability: float | None
    ask_probability: float | None
    last_price: float | None
    midpoint_probability: float
    spread: float | None
    liquidity: float | None
    volume: float | None
    market_url: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SportsbookEventRecord:
    provider: str
    provider_event_id: str
    event_name: str
    league: str | None
    home_team: str | None
    away_team: str | None
    normalized_event_key: str
    start_time: datetime | None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SportsbookLine:
    provider: str
    provider_event_id: str
    event_name: str
    league: str | None
    home_team: str | None
    away_team: str | None
    normalized_event_key: str
    start_time: datetime | None
    bookmaker: str
    market_type: str
    selection: str
    american_odds: int | None
    decimal_odds: float | None
    implied_probability: float
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectionResult:
    ok: bool
    message: str
    prediction_markets: list[PredictionMarketQuote] = field(default_factory=list)
    sportsbook_events: list[SportsbookEventRecord] = field(default_factory=list)
    sportsbook_lines: list[SportsbookLine] = field(default_factory=list)


@dataclass(frozen=True)
class PersistResult:
    records_saved: int
    snapshots_saved: int = 0
    parents_upserted: int = 0


class CollectorAdapter(ABC):
    source_name: str

    @abstractmethod
    async def collect(self) -> CollectionResult:
        """Collect source data and normalize it into Nautilus DTOs."""

    @abstractmethod
    def persist(self, db, result: CollectionResult) -> PersistResult:
        """Persist normalized records and return save counts."""
