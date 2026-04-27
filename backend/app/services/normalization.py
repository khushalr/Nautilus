from __future__ import annotations

import json
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
    "atlanta hawks": "atl-hawks",
    "brooklyn nets": "bkn",
    "charlotte hornets": "cha",
    "cleveland cavaliers": "cle",
    "dallas mavericks": "dal-mavs",
    "denver nuggets": "den-nuggets",
    "houston rockets": "hou",
    "indiana pacers": "ind",
    "la clippers": "lac-clippers",
    "los angeles clippers": "lac-clippers",
    "memphis grizzlies": "mem",
    "miami heat": "mia-heat",
    "milwaukee bucks": "mil",
    "minnesota timberwolves": "min",
    "new orleans pelicans": "nop",
    "oklahoma city thunder": "okc",
    "orlando magic": "orl",
    "phoenix suns": "phx",
    "portland trail blazers": "por",
    "sacramento kings": "sac",
    "san antonio spurs": "sas",
    "toronto raptors": "tor-raptors",
    "utah jazz": "uta",
    "washington wizards": "wsh",
    "arizona diamondbacks": "ari-dbacks",
    "atlanta braves": "atl-braves",
    "baltimore orioles": "bal-orioles",
    "boston red sox": "bos-red-sox",
    "chicago cubs": "chc",
    "chicago white sox": "chw",
    "cincinnati reds": "cin",
    "cleveland guardians": "cle-guardians",
    "colorado rockies": "col",
    "detroit tigers": "det-tigers",
    "houston astros": "hou-astros",
    "kansas city royals": "kc-royals",
    "los angeles angels": "laa",
    "miami marlins": "mia-marlins",
    "milwaukee brewers": "mil-brewers",
    "minnesota twins": "min-twins",
    "new york mets": "nym",
    "oakland athletics": "oak",
    "athletics": "oak",
    "philadelphia phillies": "phi-phillies",
    "pittsburgh pirates": "pit-pirates",
    "san francisco giants": "sf-giants",
    "seattle mariners": "sea-mariners",
    "st louis cardinals": "stl",
    "st. louis cardinals": "stl",
    "tampa bay rays": "tb-rays",
    "texas rangers": "tex",
    "washington nationals": "wsh-nationals",
    "anaheim ducks": "ana",
    "boston bruins": "bos-bruins",
    "buffalo sabres": "buf-sabres",
    "calgary flames": "cgy",
    "carolina hurricanes": "car-hurricanes",
    "chicago blackhawks": "chi-blackhawks",
    "colorado avalanche": "col-avs",
    "columbus blue jackets": "cbj",
    "dallas stars": "dal-stars",
    "detroit red wings": "det-red-wings",
    "edmonton oilers": "edm",
    "florida panthers": "fla",
    "los angeles kings": "la-kings",
    "minnesota wild": "min-wild",
    "montreal canadiens": "mtl",
    "nashville predators": "nsh",
    "new jersey devils": "njd",
    "new york islanders": "nyi",
    "new york rangers": "nyr",
    "ottawa senators": "ott",
    "philadelphia flyers": "phi-flyers",
    "pittsburgh penguins": "pit-penguins",
    "san jose sharks": "sj",
    "seattle kraken": "sea-kraken",
    "st louis blues": "stl-blues",
    "st. louis blues": "stl-blues",
    "tampa bay lightning": "tbl",
    "toronto maple leafs": "tor-leafs",
    "vancouver canucks": "van",
    "vegas golden knights": "vgk",
    "washington capitals": "wsh-capitals",
    "winnipeg jets": "wpg",
}

GENERIC_LEAGUES = {"", "sports", "sport", "unknown-league"}

LEAGUE_ALIASES: dict[str, str] = {
    "americanfootballnfl": "nfl",
    "american-football-nfl": "nfl",
    "footballnfl": "nfl",
    "nfl": "nfl",
    "basketballnba": "nba",
    "basketball-nba": "nba",
    "nba": "nba",
    "baseballmlb": "mlb",
    "baseball-mlb": "mlb",
    "mlb": "mlb",
    "icehockeynhl": "nhl",
    "ice-hockey-nhl": "nhl",
    "hockeynhl": "nhl",
    "nhl": "nhl",
}

LEAGUE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("nba", "nba"),
    ("nfl", "nfl"),
    ("mlb", "mlb"),
    ("nhl", "nhl"),
)


@dataclass(frozen=True)
class EventMatch:
    event: object
    normalized_event_key: str
    confidence_score: float
    league_score: float
    team_score: float
    date_score: float
    fuzzy_score: float
    match_type: str = "fuzzy"
    reason: str = ""
    inferred_market_normalized_event_key: str | None = None


def slugify(value: str) -> str:
    ascii_value = normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def normalize_team_name(team_name: str) -> str:
    cleaned = re.sub(r"\s+", " ", team_name.lower().strip())
    cleaned = cleaned.replace(".", "")
    return TEAM_ALIASES.get(cleaned, slugify(cleaned))


def normalize_league(league: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", str(league or "").lower().strip())
    if not cleaned:
        return "unknown-league"
    slug = slugify(cleaned)
    compact = re.sub(r"[^a-z0-9]+", "", cleaned)
    return LEAGUE_ALIASES.get(compact) or LEAGUE_ALIASES.get(slug) or slug


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
    participants = _team_aliases_in_text(event_name)
    if not participants:
        participants = re.split(r"\s+(?:vs\.?|v\.?|at|@)\s+", event_name, flags=re.IGNORECASE)
    if len(participants) == 1 and not _team_aliases_in_text(event_name):
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
    threshold: float = 0.64,
) -> EventMatch | None:
    scored = possible_event_matches(prediction_market, sportsbook_events)
    candidates = [match for match in scored if match.confidence_score >= threshold]
    if not candidates:
        return None
    return candidates[0]


def possible_event_matches(
    prediction_market: object,
    sportsbook_events: list[object],
    limit: int | None = None,
) -> list[EventMatch]:
    scored = [
        score_prediction_market_event_match(prediction_market, event)
        for event in sportsbook_events
    ]
    scored.sort(key=lambda match: match.confidence_score, reverse=True)
    return scored[:limit] if limit is not None else scored


def infer_market_normalized_event_key(
    prediction_market: object,
    sportsbook_events: list[object],
    threshold: float = 0.80,
) -> str | None:
    match = match_prediction_market_to_sportsbook_events(prediction_market, sportsbook_events, threshold=threshold)
    return match.normalized_event_key if match else None


def score_prediction_market_event_match(prediction_market: object, sportsbook_event: object) -> EventMatch:
    prediction_key = str(getattr(prediction_market, "normalized_event_key", "") or "")
    event_key = str(getattr(sportsbook_event, "normalized_event_key", "") or "")

    prediction_league = infer_market_league(prediction_market)
    event_league = normalize_league(getattr(sportsbook_event, "league", None))
    league_score = _league_match_score(prediction_league, event_league)

    prediction_start = getattr(prediction_market, "start_time", None)
    event_start = getattr(sportsbook_event, "start_time", None)
    date_score = _date_match_score(prediction_start, event_start)

    prediction_participants = _participants_from_market(prediction_market)
    event_participants = _participants_from_sportsbook_event(sportsbook_event)
    participant_team_score = _team_match_score(prediction_participants, event_participants)
    title_team_score = _title_team_match_score(prediction_market, sportsbook_event)
    team_score = max(participant_team_score, title_team_score)
    fuzzy_score = max(
        fuzzy_event_score(prediction_key, event_key) if prediction_key and event_key else 0.0,
        _event_title_fuzzy_score(prediction_market, sportsbook_event),
    )

    exact_key_bonus = 0.08 if prediction_key and event_key and prediction_key == event_key else 0.0
    confidence = min(
        1.0,
        (0.22 * league_score)
        + (0.48 * team_score)
        + (0.20 * date_score)
        + (0.10 * fuzzy_score)
        + exact_key_bonus,
    )
    match_type = "fuzzy"
    reason = "league/team/date/title fuzzy match"
    if prediction_key and event_key and prediction_key == event_key:
        confidence = max(confidence, 0.96)
        match_type = "exact_normalized_event_key"
        reason = "normalized_event_key matched exactly"

    if match_type != "exact_normalized_event_key":
        if team_score < 0.58:
            confidence = min(confidence, 0.55)
        if date_score == 0.0 and prediction_start is not None and event_start is not None:
            confidence = min(confidence, 0.58)
        if league_score < 0.35:
            confidence = min(confidence, 0.58)

    inferred_key = event_key if confidence >= 0.80 else None

    return EventMatch(
        event=sportsbook_event,
        normalized_event_key=event_key,
        confidence_score=confidence,
        league_score=league_score,
        team_score=team_score,
        date_score=date_score,
        fuzzy_score=fuzzy_score,
        match_type=match_type,
        reason=reason,
        inferred_market_normalized_event_key=inferred_key,
    )


def infer_market_league(prediction_market: object) -> str:
    explicit = normalize_league(getattr(prediction_market, "league", None))
    if explicit not in GENERIC_LEAGUES:
        return explicit
    inferred = infer_league_from_text(_market_search_text(prediction_market))
    return inferred or explicit


def infer_league_from_text(text: str) -> str | None:
    searchable = f" {slugify(text).replace('-', ' ')} "
    for keyword, league in LEAGUE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", searchable):
            return league
    return None


def team_mention_score(text: str, team_name: str | None) -> float:
    if not team_name:
        return 0.0
    text_slug = f"-{slugify(text)}-"
    team_slug = slugify(team_name)
    if team_slug and f"-{team_slug}-" in text_slug:
        return 1.0

    normalized_team = normalize_team_name(team_name)
    for alias, canonical in TEAM_ALIASES.items():
        alias_slug = slugify(alias)
        if canonical == normalized_team and alias_slug and f"-{alias_slug}-" in text_slug:
            return 0.92

    team_tokens = [token for token in team_slug.split("-") if token]
    text_tokens = set(token for token in text_slug.strip("-").split("-") if token)
    distinctive_tokens = [
        token
        for token in team_tokens
        if len(token) >= 4 and token not in {"the", "new", "los", "san", "bay", "city", "st", "saint"}
    ]
    if distinctive_tokens and distinctive_tokens[-1] in text_tokens:
        return 0.86
    if normalized_team and f"-{normalized_team}-" in text_slug:
        return 0.80

    best_ratio = 0.0
    text_joined = " ".join(text_tokens)
    for token in distinctive_tokens:
        best_ratio = max(best_ratio, SequenceMatcher(None, token, text_joined).ratio())
    return min(best_ratio, 0.70)


def team_mention_position(text: str, team_name: str | None) -> int | None:
    if not team_name:
        return None
    text_slug = f"-{slugify(text)}-"
    candidates = [slugify(team_name)]
    normalized_team = normalize_team_name(team_name)
    candidates.extend(slugify(alias) for alias, canonical in TEAM_ALIASES.items() if canonical == normalized_team)
    team_tokens = [token for token in slugify(team_name).split("-") if token]
    if team_tokens:
        candidates.append(team_tokens[-1])

    positions = [
        text_slug.find(f"-{candidate}-")
        for candidate in candidates
        if candidate and text_slug.find(f"-{candidate}-") >= 0
    ]
    return min(positions) if positions else None


def _participants_from_market(prediction_market: object) -> list[str]:
    event_name = _market_title_text(prediction_market)
    participants = parse_event_participants(event_name)
    participants.extend(_team_aliases_in_text(event_name))
    selection = str(getattr(prediction_market, "selection", "") or "")
    if selection and selection.lower() not in {"yes", "no"}:
        participants.append(selection)
    return [normalize_team_name(participant) for participant in participants if participant]


def _team_aliases_in_text(text: str) -> list[str]:
    text_lower = text.lower()
    matches: list[str] = []
    seen: set[str] = set()
    for alias, canonical in sorted(TEAM_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if canonical in seen:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", text_lower):
            matches.append(canonical)
            seen.add(canonical)
    return matches


def _participants_from_sportsbook_event(sportsbook_event: object) -> list[str]:
    participants = [
        getattr(sportsbook_event, "home_team", None),
        getattr(sportsbook_event, "away_team", None),
    ]
    if not any(participants):
        participants = parse_event_participants(str(getattr(sportsbook_event, "event_name", "") or ""))
    return [normalize_team_name(str(participant)) for participant in participants if participant]


def _league_match_score(prediction_league: str, event_league: str) -> float:
    if prediction_league == event_league:
        return 1.0
    if prediction_league in GENERIC_LEAGUES or event_league in GENERIC_LEAGUES:
        return 0.45
    return min(SequenceMatcher(None, prediction_league, event_league).ratio(), 0.65)


def _title_team_match_score(prediction_market: object, sportsbook_event: object) -> float:
    text = _market_title_text(prediction_market)
    team_scores = [
        team_mention_score(text, getattr(sportsbook_event, "home_team", None)),
        team_mention_score(text, getattr(sportsbook_event, "away_team", None)),
    ]
    strong_scores = [score for score in team_scores if score >= 0.78]
    if len(strong_scores) >= 2:
        return 1.0
    if len(strong_scores) == 1:
        return 0.82
    return max(team_scores or [0.0])


def _event_title_fuzzy_score(prediction_market: object, sportsbook_event: object) -> float:
    text = _market_title_text(prediction_market)
    event_name = str(getattr(sportsbook_event, "event_name", "") or "")
    home_team = str(getattr(sportsbook_event, "home_team", "") or "")
    away_team = str(getattr(sportsbook_event, "away_team", "") or "")
    variants = [
        event_name,
        f"{away_team} at {home_team}",
        f"{away_team} vs {home_team}",
        f"{home_team} vs {away_team}",
        f"{home_team} against {away_team}",
        f"{away_team} against {home_team}",
    ]
    text_slug = slugify(text)
    return max(
        (SequenceMatcher(None, text_slug, slugify(variant)).ratio() for variant in variants if variant.strip()),
        default=0.0,
    )


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
    try:
        hour_delta = abs((left - right).total_seconds()) / 3600
    except TypeError:
        hour_delta = None
    if hour_delta is not None:
        if hour_delta <= 18:
            return 1.0
        if hour_delta <= 36:
            return 0.80
        if hour_delta <= 72:
            return 0.35
        return 0.0

    day_delta = abs((left.date() - right.date()).days)
    if day_delta == 0:
        return 1.0
    if day_delta == 1:
        return 0.80
    if day_delta <= 3:
        return 0.35
    return 0.0


def _market_search_text(prediction_market: object) -> str:
    parts = [
        str(getattr(prediction_market, "event_name", "") or ""),
        str(getattr(prediction_market, "selection", "") or ""),
        str(getattr(prediction_market, "league", "") or ""),
        str(getattr(prediction_market, "market_type", "") or ""),
    ]
    extra = getattr(prediction_market, "extra", None)
    if isinstance(extra, dict):
        parts.extend(_market_metadata_values(extra))
    return " ".join(part for part in parts if part)


def _market_title_text(prediction_market: object) -> str:
    return " ".join(
        part
        for part in (
            str(getattr(prediction_market, "event_name", "") or ""),
            str(getattr(prediction_market, "selection", "") or ""),
        )
        if part
    )


def _market_metadata_values(extra: dict) -> list[str]:
    raw_market = extra.get("raw_market")
    if isinstance(raw_market, dict):
        values = [str(raw_market.get("outcome") or "")]
        market_payload = raw_market.get("market")
        if isinstance(market_payload, dict):
            values.extend(_selected_payload_values(market_payload))
        return [value for value in values if value]
    return _selected_payload_values(extra)


def _selected_payload_values(payload: dict) -> list[str]:
    values: list[str] = []
    for key in ("question", "title", "description", "category", "sport", "league", "market_slug", "slug"):
        value = payload.get(key)
        if isinstance(value, str):
            values.append(value)
    tags = payload.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict):
                for key in ("label", "name", "slug"):
                    value = tag.get(key)
                    if isinstance(value, str):
                        values.append(value)
            elif isinstance(tag, str):
                values.append(tag)
    try:
        metadata = payload.get("metadata")
        if isinstance(metadata, str):
            decoded = json.loads(metadata)
            if isinstance(decoded, dict):
                values.extend(_selected_payload_values(decoded))
    except json.JSONDecodeError:
        pass
    return values
