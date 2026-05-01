from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Select, and_, desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models import (
    AlertRule,
    FairValueSnapshot,
    Market,
    PredictionMarketSnapshot,
    SportsbookEvent,
    SportsbookOddsSnapshot,
    UserModel,
)
from app.services.normalization import infer_market_league, normalize_team_name, slugify
from app.schemas import (
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    FairValueSnapshotOut,
    MarketDetailOut,
    MarketOut,
    OpportunityHistoryRow,
    OpportunityScannerOut,
    UserModelCreate,
    UserModelOut,
)

router = APIRouter()


def _latest_fair_value_query() -> Select:
    ranked = (
        select(
            FairValueSnapshot.id.label("id"),
            func.row_number()
            .over(partition_by=FairValueSnapshot.market_id, order_by=FairValueSnapshot.observed_at.desc())
            .label("rank"),
        )
        .subquery()
    )
    return select(FairValueSnapshot).join(ranked, FairValueSnapshot.id == ranked.c.id).where(ranked.c.rank == 1)


@router.get("/markets", response_model=list[MarketOut])
def list_markets(
    db: Session = Depends(get_db),
    league: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[Market]:
    stmt = select(Market).order_by(Market.start_time.asc().nulls_last(), Market.event_name.asc()).limit(limit)
    if league:
        stmt = stmt.where(Market.league == league)
    if source:
        stmt = stmt.where(Market.source == source)
    return list(db.scalars(stmt))


@router.get("/markets/{market_id}", response_model=MarketDetailOut)
def get_market(market_id: str, db: Session = Depends(get_db)) -> MarketDetailOut:
    market = db.get(Market, market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")

    latest_fair_value = db.scalar(
        select(FairValueSnapshot)
        .where(FairValueSnapshot.market_id == market_id)
        .order_by(desc(FairValueSnapshot.observed_at))
        .limit(1)
    )
    prediction_snapshots = list(
        db.scalars(
            select(PredictionMarketSnapshot)
            .where(PredictionMarketSnapshot.market_id == market_id)
            .order_by(PredictionMarketSnapshot.observed_at.desc())
            .limit(200)
        )
    )
    fair_value_history = list(
        db.scalars(
            select(FairValueSnapshot)
            .where(FairValueSnapshot.market_id == market_id)
            .order_by(FairValueSnapshot.observed_at.desc())
            .limit(200)
        )
    )
    sportsbook_odds = _sportsbook_odds_for_detail(db, market, latest_fair_value)
    return MarketDetailOut(
        market=market,
        latest_fair_value=latest_fair_value,
        prediction_snapshots=prediction_snapshots,
        fair_value_history=fair_value_history,
        sportsbook_odds=sportsbook_odds,
    )


def _sportsbook_odds_for_detail(
    db: Session,
    market: Market,
    latest_fair_value: FairValueSnapshot | None,
) -> list[SportsbookOddsSnapshot]:
    explanation = latest_fair_value.explanation_json if latest_fair_value else {}
    matched_event = explanation.get("matched_event") if isinstance(explanation, dict) else None
    matched_event_id = matched_event.get("event_id") if isinstance(matched_event, dict) else None
    bookmakers = explanation.get("bookmakers") if isinstance(explanation, dict) else None
    matched_selections = {
        str(book.get("selection"))
        for book in bookmakers or []
        if isinstance(book, dict) and book.get("selection")
    }

    if matched_event_id and matched_selections:
        return list(
            db.scalars(
                select(SportsbookOddsSnapshot)
                .where(
                    and_(
                        SportsbookOddsSnapshot.event_id == str(matched_event_id),
                        SportsbookOddsSnapshot.selection.in_(matched_selections),
                    )
                )
                .order_by(SportsbookOddsSnapshot.observed_at.desc())
                .limit(100)
            )
        )

    return list(
        db.scalars(
            select(SportsbookOddsSnapshot)
            .join(SportsbookEvent)
            .where(
                and_(
                    SportsbookEvent.normalized_event_key == market.normalized_event_key,
                    SportsbookOddsSnapshot.selection == market.selection,
                )
            )
            .order_by(SportsbookOddsSnapshot.observed_at.desc())
            .limit(100)
        )
    )


@router.get("/opportunities", response_model=list[OpportunityScannerOut], response_model_exclude_unset=True)
def list_opportunities(
    db: Session = Depends(get_db),
    min_net_edge: float = Query(default=-1.0),
    min_confidence: float = Query(default=0.0),
    league: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    include_debug: bool = Query(default=False),
    include_raw: bool = Query(default=False),
) -> list[OpportunityScannerOut]:
    latest = _latest_fair_value_query().subquery()
    stmt = (
        select(Market, FairValueSnapshot)
        .join(FairValueSnapshot, FairValueSnapshot.market_id == Market.id)
        .join(latest, latest.c.id == FairValueSnapshot.id)
        .where(
            and_(
                FairValueSnapshot.net_edge >= min_net_edge,
                FairValueSnapshot.confidence_score >= min_confidence,
            )
        )
        .order_by(FairValueSnapshot.net_edge.desc(), FairValueSnapshot.confidence_score.desc())
        .limit(min(limit * 4, 500))
    )
    if league:
        stmt = stmt.where(Market.league == league)

    rows = [
        _opportunity_scanner_row(market, fair_value, include_debug=include_debug, include_raw=include_raw)
        for market, fair_value in db.execute(stmt).all()
    ]
    return _dedupe_scanner_rows(rows)[:limit]


@router.get("/opportunities/{market_id}", response_model=MarketDetailOut)
def get_opportunity(market_id: str, db: Session = Depends(get_db)) -> MarketDetailOut:
    return get_market(market_id, db)


@router.get("/opportunities/{market_id}/history", response_model=list[OpportunityHistoryRow])
def get_opportunity_history(
    market_id: str,
    db: Session = Depends(get_db),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[OpportunityHistoryRow]:
    market = db.get(Market, market_id)
    if market is None:
        raise HTTPException(status_code=404, detail="Market not found")

    rows = list(
        db.scalars(
            select(FairValueSnapshot)
            .where(FairValueSnapshot.market_id == market_id)
            .order_by(FairValueSnapshot.observed_at.asc())
            .limit(limit)
        )
    )
    return [_history_row(market, row) for row in rows]


def _history_row(market: Market, fair_value: FairValueSnapshot) -> OpportunityHistoryRow:
    market_probability = fair_value.market_probability
    fair_probability = fair_value.fair_probability
    gross_edge = fair_value.gross_edge
    net_edge = fair_value.net_edge

    explanation = fair_value.explanation_json if isinstance(fair_value.explanation_json, dict) else {}
    market_probability_explanation = explanation.get("market_probability")
    orientation = (
        market_probability_explanation.get("orientation")
        if isinstance(market_probability_explanation, dict)
        else None
    )
    if (
        market.market_type in {"futures", "awards", "outrights"}
        and market.selection.lower().strip() == "no"
        and orientation != "positive_yes_complemented_from_no"
    ):
        penalty_total = fair_value.gross_edge - fair_value.net_edge
        market_probability = _complement_probability(fair_value.market_probability)
        fair_probability = _complement_probability(fair_value.fair_probability)
        gross_edge = fair_probability - market_probability
        net_edge = gross_edge - penalty_total

    return OpportunityHistoryRow(
        timestamp=fair_value.observed_at,
        market_probability=market_probability,
        fair_probability=fair_probability,
        gross_edge=gross_edge,
        net_edge=net_edge,
        confidence_score=fair_value.confidence_score,
    )


def _opportunity_scanner_row(
    market: Market,
    fair_value: FairValueSnapshot,
    *,
    include_debug: bool,
    include_raw: bool,
) -> OpportunityScannerOut:
    explanation = fair_value.explanation_json if isinstance(fair_value.explanation_json, dict) else {}
    matched_event = explanation.get("matched_event") if isinstance(explanation.get("matched_event"), dict) else {}
    market_probability = explanation.get("market_probability") if isinstance(explanation.get("market_probability"), dict) else {}
    explanation_market = explanation.get("market") if isinstance(explanation.get("market"), dict) else {}
    bookmakers = explanation.get("bookmakers") if isinstance(explanation.get("bookmakers"), list) else []
    selected_bookmakers = explanation.get("selected_bookmakers")
    sportsbooks_used = (
        [str(bookmaker) for bookmaker in selected_bookmakers if bookmaker]
        if isinstance(selected_bookmakers, list)
        else [
            str(book.get("bookmaker"))
            for book in bookmakers
            if isinstance(book, dict) and book.get("bookmaker")
        ]
    )
    matched_selection = next(
        (
            str(book.get("selection"))
            for book in bookmakers
            if isinstance(book, dict) and book.get("selection")
        ),
        None,
    )
    display_outcome = _string_or_none(explanation_market.get("display_outcome")) or _string_or_none(
        market_probability.get("display_outcome")
    )

    payload = OpportunityScannerOut(
        market_id=market.id,
        title=market.event_name,
        source=market.source,
        external_id=market.external_id,
        league=_display_league(market, matched_event),
        market_type=_display_market_type(market.market_type),
        outcome=display_outcome,
        display_outcome=display_outcome,
        start_time=market.start_time,
        status=market.status,
        market_url=market.market_url,
        market_probability=fair_value.market_probability,
        fair_probability=fair_value.fair_probability,
        gross_edge=fair_value.gross_edge,
        net_edge=fair_value.net_edge,
        spread=fair_value.spread,
        liquidity=fair_value.liquidity,
        confidence_score=fair_value.confidence_score,
        matched_sportsbook_category=_string_or_none(matched_event.get("event_name")),
        matched_selection=matched_selection,
        match_confidence=_float_or_none(matched_event.get("confidence_score")),
        sportsbooks_used=sportsbooks_used,
        last_updated=fair_value.observed_at,
    )
    if include_debug:
        payload.assumptions = fair_value.assumptions
        payload.explanation_json = explanation
    if include_raw:
        payload.market_extra = market.extra
    return payload


def _dedupe_scanner_rows(rows: list[OpportunityScannerOut]) -> list[OpportunityScannerOut]:
    deduped: dict[str, OpportunityScannerOut] = {}
    for row in rows:
        key = _canonical_opportunity_key(row)
        current = deduped.get(key)
        if current is None or _row_rank(row) > _row_rank(current):
            deduped[key] = row
    return sorted(
        deduped.values(),
        key=lambda row: (row.net_edge, row.confidence_score, row.last_updated),
        reverse=True,
    )


def _row_rank(row: OpportunityScannerOut) -> tuple[float, float, object]:
    return (row.net_edge, row.confidence_score, row.last_updated)


def _canonical_opportunity_key(row: OpportunityScannerOut) -> str:
    market_type = _display_market_type(row.market_type)
    outcome = normalize_team_name(row.display_outcome or row.outcome or row.matched_selection or row.title)
    if market_type == "h2h_game":
        matched = row.matched_sportsbook_category or row.title
        start_date = row.start_time.date().isoformat() if row.start_time else "unknown-date"
        return "|".join(
            (
                row.source,
                market_type,
                slugify(row.league or "unknown"),
                outcome,
                slugify(matched),
                start_date,
            )
        )
    category = row.matched_sportsbook_category or row.title
    return "|".join((row.source, market_type, slugify(category), outcome))


def _display_market_type(market_type: str | None) -> str:
    return "h2h_game" if market_type == "h2h" else str(market_type or "other")


def _display_league(market: Market, matched_event: dict) -> str | None:
    explicit = market.league
    if explicit and slugify(explicit) not in {"sports", "sport", "unknown-league"}:
        return explicit.upper() if explicit.lower() in {"nba", "nfl", "mlb", "nhl"} else explicit
    inferred = infer_market_league(market)
    if inferred and inferred not in {"sports", "sport", "unknown-league"}:
        return inferred.upper()
    event_name = _string_or_none(matched_event.get("event_name"))
    event_league = infer_market_league(type("MatchedEventText", (), {"event_name": event_name or "", "selection": "", "league": ""})())
    if event_league and event_league not in {"sports", "sport", "unknown-league"}:
        return event_league.upper()
    return explicit


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _float_or_none(value: object) -> float | None:
    return value if isinstance(value, float | int) else None


def _complement_probability(value: float) -> float:
    return max(0.0, min(1.0, 1 - value))


@router.get("/fair-values/latest", response_model=list[FairValueSnapshotOut])
def latest_fair_values(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[FairValueSnapshot]:
    stmt = _latest_fair_value_query().order_by(FairValueSnapshot.observed_at.desc()).limit(limit)
    return list(db.scalars(stmt))


@router.post("/user-models", response_model=UserModelOut, status_code=201)
def create_user_model(payload: UserModelCreate, db: Session = Depends(get_db)) -> UserModel:
    config = {**get_settings().default_user_model, **payload.config}
    model = UserModel(name=payload.name, config=config)
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


@router.get("/user-models", response_model=list[UserModelOut])
def list_user_models(db: Session = Depends(get_db)) -> list[UserModel]:
    return list(db.scalars(select(UserModel).order_by(UserModel.created_at.desc())))


@router.post("/alerts", response_model=AlertRuleOut, status_code=201)
def create_alert(payload: AlertRuleCreate, db: Session = Depends(get_db)) -> AlertRule:
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/alerts", response_model=list[AlertRuleOut])
def list_alerts(db: Session = Depends(get_db)) -> list[AlertRule]:
    return list(db.scalars(select(AlertRule).order_by(AlertRule.created_at.desc())))


@router.patch("/alerts/{alert_id}", response_model=AlertRuleOut)
def update_alert(alert_id: str, payload: AlertRuleUpdate, db: Session = Depends(get_db)) -> AlertRule:
    rule = db.get(AlertRule, alert_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/alerts/{alert_id}", status_code=204)
def delete_alert(alert_id: str, db: Session = Depends(get_db)) -> Response:
    rule = db.get(AlertRule, alert_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    db.delete(rule)
    db.commit()
    return Response(status_code=204)
