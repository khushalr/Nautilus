from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from app.services.normalization import TEAM_ALIASES, parse_event_participants

PREDICTION_MARKET_TYPES = {"h2h", "h2h_game", "futures", "awards", "totals", "spread", "other"}

FUTURES_TERMS = (
    "win the championship",
    "win the finals",
    "win the world cup",
    "win the stanley cup",
    "win the super bowl",
    "win the nba finals",
    "win the eastern conference finals",
    "win the western conference finals",
    "nba finals",
    "conference finals",
    "stanley cup",
    "super bowl",
    "world cup",
    "division winner",
    "championship",
    "world series",
    "world cup",
    "stanley cup",
    "super bowl",
    "playoffs",
)

AWARDS_TERMS = (
    "mvp",
    "rookie of the year",
    "defensive player of the year",
    "coach of the year",
    "cy young",
    "heisman",
    "ballon d",
    "award",
)

TOTALS_TERMS = (
    "over/under",
    "over under",
    " total ",
    "totals",
    "combined points",
    "combined runs",
    "combined goals",
)

SPREAD_TERMS = (
    "spread",
    "handicap",
    "cover",
    "covers",
    "point spread",
    "puck line",
    "run line",
)

H2H_TERMS = (
    " vs ",
    " vs. ",
    " at ",
    " @ ",
    " beat ",
    " beats ",
    " defeat ",
    " defeats ",
    " win against ",
)


def classify_prediction_market(
    *,
    title: str,
    selection: str | None = None,
    league: str | None = None,
    start_time: datetime | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> str:
    text = _search_text(title, selection, league, raw_payload)
    if _contains_any(text, AWARDS_TERMS):
        return "awards"
    if _contains_any(text, FUTURES_TERMS):
        return "futures"
    if _contains_any(text, TOTALS_TERMS):
        return "totals"
    if _contains_any(text, SPREAD_TERMS):
        return "spread"
    if _looks_like_h2h(title, selection, start_time, raw_payload):
        return "h2h_game"
    return "other"


def market_priority(market_type: str, start_time: datetime | None = None) -> tuple[int, int]:
    type_priority = {
        "h2h_game": 0,
        "h2h": 0,
        "totals": 1,
        "spread": 2,
        "other": 3,
        "futures": 4,
        "awards": 5,
    }.get(market_type, 6)
    start_priority = 0 if _is_upcoming(start_time) else 1
    return type_priority, start_priority


def should_compute_h2h_fair_value(market_type: str | None) -> bool:
    return market_type in {"h2h", "h2h_game"}


def effective_prediction_market_type(market: object) -> str:
    stored_type = str(getattr(market, "market_type", "") or "").lower()
    if stored_type == "h2h":
        return "h2h_game"
    if stored_type in PREDICTION_MARKET_TYPES:
        return stored_type
    return classify_prediction_market(
        title=str(getattr(market, "event_name", "") or ""),
        selection=str(getattr(market, "selection", "") or ""),
        league=str(getattr(market, "league", "") or ""),
        start_time=getattr(market, "start_time", None),
        raw_payload=getattr(market, "extra", None),
    )


def _looks_like_h2h(
    title: str,
    selection: str | None,
    start_time: datetime | None,
    raw_payload: dict[str, Any] | None,
) -> bool:
    text = f" {title.lower()} "
    participants = parse_event_participants(title)
    has_h2h_language = _contains_any(text, H2H_TERMS)
    if len(participants) >= 2 and (has_h2h_language or start_time is not None):
        return True
    if has_h2h_language and _known_team_mentions(title) >= 2:
        return True

    outcomes = _raw_outcomes(raw_payload)
    if len(outcomes) == 2 and start_time is not None:
        normalized_outcomes = {outcome.lower() for outcome in outcomes}
        if normalized_outcomes != {"yes", "no"}:
            return True

    if selection and selection.lower() not in {"yes", "no"} and has_h2h_language:
        return True

    return False


def _known_team_mentions(title: str) -> int:
    text = title.lower()
    seen: set[str] = set()
    for alias, canonical in TEAM_ALIASES.items():
        if canonical in seen:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", text):
            seen.add(canonical)
    return len(seen)


def _search_text(
    title: str,
    selection: str | None,
    league: str | None,
    raw_payload: dict[str, Any] | None,
) -> str:
    parts = [title, selection or "", league or ""]
    if raw_payload:
        parts.extend(_selected_payload_values(_payload_market(raw_payload)))
    return f" {' '.join(parts).lower()} "


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_upcoming(start_time: datetime | None) -> bool:
    if start_time is None:
        return False
    now = datetime.now(UTC)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=UTC)
    return start_time >= now


def _raw_outcomes(raw_payload: dict[str, Any] | None) -> list[str]:
    if not raw_payload:
        return []
    payload = _payload_market(raw_payload)
    outcomes = payload.get("outcomes")
    if isinstance(outcomes, str):
        try:
            parsed = json.loads(outcomes)
        except json.JSONDecodeError:
            return [outcomes]
        outcomes = parsed
    if isinstance(outcomes, list):
        return [str(outcome) for outcome in outcomes if str(outcome)]
    return []


def _payload_market(raw_payload: dict[str, Any]) -> dict[str, Any]:
    raw_market = raw_payload.get("raw_market")
    if isinstance(raw_market, dict):
        nested_market = raw_market.get("market")
        if isinstance(nested_market, dict):
            return nested_market
        return raw_market
    nested_market = raw_payload.get("market")
    if isinstance(nested_market, dict):
        return nested_market
    return raw_payload


def _selected_payload_values(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("question", "title", "subtitle", "category", "event_ticker", "series_ticker", "ticker"):
        value = payload.get(key)
        if isinstance(value, str):
            values.append(value)
    tags = payload.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict):
                values.extend(str(tag.get(key) or "") for key in ("label", "name", "slug"))
            elif isinstance(tag, str):
                values.append(tag)
    return [re.sub(r"\s+", " ", value).strip() for value in values if value]
