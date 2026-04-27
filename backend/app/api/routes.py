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
from app.schemas import (
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    FairValueSnapshotOut,
    MarketDetailOut,
    MarketOut,
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
        .limit(limit)
    )
    if league:
        stmt = stmt.where(Market.league == league)

    return [
        _opportunity_scanner_row(market, fair_value, include_debug=include_debug, include_raw=include_raw)
        for market, fair_value in db.execute(stmt).all()
    ]


@router.get("/opportunities/{market_id}", response_model=MarketDetailOut)
def get_opportunity(market_id: str, db: Session = Depends(get_db)) -> MarketDetailOut:
    return get_market(market_id, db)


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
        league=market.league,
        market_type=market.market_type,
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


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _float_or_none(value: object) -> float | None:
    return value if isinstance(value, float | int) else None


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
