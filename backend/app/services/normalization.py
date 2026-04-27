from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from unicodedata import normalize


TEAM_ALIASES: dict[str, str] = {
    "arizona cardinals": "ari",
    "cardinals": "ari",
    "atlanta falcons": "atl",
    "falcons": "atl",
    "baltimore ravens": "bal",
    "ravens": "bal",
    "buffalo bills": "buf",
    "bills": "buf",
    "carolina panthers": "car",
    "panthers": "car",
    "chicago bears": "chi",
    "bears": "chi",
    "dallas cowboys": "dal",
    "cowboys": "dal",
    "denver broncos": "den",
    "broncos": "den",
    "detroit lions": "det",
    "lions": "det",
    "green bay packers": "gb",
    "packers": "gb",
    "kansas city chiefs": "kc",
    "chiefs": "kc",
    "las vegas raiders": "lv",
    "raiders": "lv",
    "los angeles chargers": "lac",
    "chargers": "lac",
    "los angeles rams": "lar",
    "rams": "lar",
    "miami dolphins": "mia",
    "dolphins": "mia",
    "new england patriots": "ne",
    "patriots": "ne",
    "new york giants": "nyg",
    "giants": "nyg",
    "new york jets": "nyj",
    "jets": "nyj",
    "philadelphia eagles": "phi",
    "eagles": "phi",
    "pittsburgh steelers": "pit",
    "steelers": "pit",
    "san francisco 49ers": "sf",
    "49ers": "sf",
    "seattle seahawks": "sea",
    "seahawks": "sea",
    "tampa bay buccaneers": "tb",
    "buccaneers": "tb",
    "tennessee titans": "ten",
    "titans": "ten",
    "washington commanders": "was",
    "commanders": "was",
    "boston celtics": "bos",
    "celtics": "bos",
    "new york knicks": "nyk",
    "knicks": "nyk",
    "los angeles lakers": "lal",
    "lakers": "lal",
    "golden state warriors": "gsw",
    "warriors": "gsw",
    "los angeles dodgers": "lad",
    "dodgers": "lad",
    "san diego padres": "sd",
    "padres": "sd",
    "new york yankees": "nyy",
    "yankees": "nyy",
    "toronto blue jays": "tor",
    "blue jays": "tor",
}


@dataclass(frozen=True)
class EventMatch:
    event: object
    normalized_event_key: str
    confidence_score: float
    league_score: float
    team_score: float
    date_score: float
    fuzzy_score: float


def slugify(value: str) -> str:
    ascii_value = normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def normalize_team_name(team_name: str) -> str:
    cleaned = re.sub(r"\s+", " ", team_name.lower().strip())
    cleaned = cleaned.replace(".", "")
    return TEAM_ALIASES.get(cleaned, slugify(cleaned))


def normalize_league(league: str | None) -> str:
    return slugify(league or "unknown-league")


def normalized_event_key(
    league: str | None,
    participants: list[str] | tuple[str, ...],
    start_time: datetime | None = None,
) -> str:
    normalized_participants = sorted(normalize_team_name(participant) for participant in participants if participant)
    date_part = start_time.date().isoformat() if start_time else "unknown-date"
    league_part = normalize_league(league)
    teams_part = "-vs-".join(normalized_participants) or "unknown-participants"
    return f"{league_part}:{date_part}:{teams_part}"


def normalized_event_key_from_name(
    league: str | None,
    event_name: str,
    start_time: datetime | None = None,
) -> str:
    participants = re.split(r"\s+(?:vs\.?|v\.?|at|@)\s+", event_name, flags=re.IGNORECASE)
    if len(participants) == 1:
        participants = re.split(r"\s+-\s+|\s+versus\s+", event_name, flags=re.IGNORECASE)
    return normalized_event_key(league, [participant.strip() for participant in participants], start_time)


def parse_event_participants(event_name: str) -> list[str]:
    participants = re.split(r"\s+(?:vs\.?|v\.?|at|@)\s+", event_name, flags=re.IGNORECASE)
    if len(participants) == 1:
        participants = re.split(r"\s+-\s+|\s+versus\s+", event_name, flags=re.IGNORECASE)
    return [participant.strip() for participant in participants if participant.strip()]


def fuzzy_event_score(left_event_key: str, right_event_key: str) -> float:
    return SequenceMatcher(None, left_event_key, right_event_key).ratio()


def match_event_by_fuzzy_key(
    target_key: str,
    candidate_keys: list[str],
    threshold: float = 0.82,
) -> str | None:
    scored = sorted(
        ((candidate, fuzzy_event_score(target_key, candidate)) for candidate in candidate_keys),
        key=lambda item: item[1],
        reverse=True,
    )
    if not scored:
        return None
    best_key, score = scored[0]
    return best_key if score >= threshold else None


def match_prediction_market_to_sportsbook_events(
    prediction_market: object,
    sportsbook_events: list[object],
    threshold: float = 0.58,
) -> EventMatch | None:
    scored = [
        score_prediction_market_event_match(prediction_market, event)
        for event in sportsbook_events
    ]
    scored = [match for match in scored if match.confidence_score >= threshold]
    if not scored:
        return None
    return max(scored, key=lambda match: match.confidence_score)


def score_prediction_market_event_match(prediction_market: object, sportsbook_event: object) -> EventMatch:
    prediction_key = str(getattr(prediction_market, "normalized_event_key", "") or "")
    event_key = str(getattr(sportsbook_event, "normalized_event_key", "") or "")

    prediction_league = normalize_league(getattr(prediction_market, "league", None))
    event_league = normalize_league(getattr(sportsbook_event, "league", None))
    league_score = 1.0 if prediction_league == event_league else SequenceMatcher(None, prediction_league, event_league).ratio()

    prediction_start = getattr(prediction_market, "start_time", None)
    event_start = getattr(sportsbook_event, "start_time", None)
    date_score = _date_match_score(prediction_start, event_start)

    prediction_participants = _participants_from_market(prediction_market)
    event_participants = _participants_from_sportsbook_event(sportsbook_event)
    team_score = _team_match_score(prediction_participants, event_participants)
    fuzzy_score = fuzzy_event_score(prediction_key, event_key) if prediction_key and event_key else 0.0

    exact_key_bonus = 0.08 if prediction_key and event_key and prediction_key == event_key else 0.0
    confidence = min(
        1.0,
        (0.25 * league_score)
        + (0.40 * team_score)
        + (0.20 * date_score)
        + (0.15 * fuzzy_score)
        + exact_key_bonus,
    )

    return EventMatch(
        event=sportsbook_event,
        normalized_event_key=event_key,
        confidence_score=confidence,
        league_score=league_score,
        team_score=team_score,
        date_score=date_score,
        fuzzy_score=fuzzy_score,
    )


def _participants_from_market(prediction_market: object) -> list[str]:
    event_name = str(getattr(prediction_market, "event_name", "") or "")
    participants = parse_event_participants(event_name)
    event_name_lower = event_name.lower()
    for alias, canonical in TEAM_ALIASES.items():
        if alias in event_name_lower:
            participants.append(canonical)
    selection = str(getattr(prediction_market, "selection", "") or "")
    if selection and selection.lower() not in {"yes", "no"}:
        participants.append(selection)
    return [normalize_team_name(participant) for participant in participants if participant]


def _participants_from_sportsbook_event(sportsbook_event: object) -> list[str]:
    participants = [
        getattr(sportsbook_event, "home_team", None),
        getattr(sportsbook_event, "away_team", None),
    ]
    if not any(participants):
        participants = parse_event_participants(str(getattr(sportsbook_event, "event_name", "") or ""))
    return [normalize_team_name(str(participant)) for participant in participants if participant]


def _team_match_score(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    overlap_score = len(left_set & right_set) / max(len(left_set), len(right_set))
    if left_set & right_set:
        overlap_score = max(overlap_score, 0.7)
    fuzzy_scores = [
        max(SequenceMatcher(None, left_team, right_team).ratio() for right_team in right_set)
        for left_team in left_set
    ]
    fuzzy_score = sum(fuzzy_scores) / len(fuzzy_scores)
    return max(overlap_score, fuzzy_score)


def _date_match_score(left: datetime | None, right: datetime | None) -> float:
    if left is None or right is None:
        return 0.5
    day_delta = abs((left.date() - right.date()).days)
    if day_delta == 0:
        return 1.0
    if day_delta == 1:
        return 0.65
    if day_delta <= 3:
        return 0.3
    return 0.0
