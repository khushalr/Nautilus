from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Select, and_, desc, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models import (
    AlertRule,
    BacktestSweepResult,
    FairValueSnapshot,
    Market,
    PaperTradeSignal,
    PredictionMarketSnapshot,
    SignalBacktestResult,
    SportsbookEvent,
    SportsbookOddsSnapshot,
    UserModel,
)
from app.services.backtesting import classify_closure_reason
from app.services.normalization import infer_market_league, normalize_team_name, slugify
from app.schemas import (
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    BacktestSweepResultOut,
    FairValueSnapshotOut,
    MarketDetailOut,
    MarketOut,
    OpportunityHistoryRow,
    OpportunityScannerOut,
    SignalPerformanceBucket,
    SignalPerformanceRow,
    SignalPerformanceSummary,
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


@router.get("/signals/performance", response_model=SignalPerformanceSummary)
def signal_performance(db: Session = Depends(get_db)) -> SignalPerformanceSummary:
    rows = _signal_result_rows(db)
    return SignalPerformanceSummary(
        **_aggregate_rows(rows),
        by_horizon=_bucket_rows(rows, lambda row: row["horizon"]),
        by_confidence_bucket=_bucket_rows(rows, lambda row: _confidence_bucket(row["confidence_score"])),
        by_market_type=_bucket_rows(rows, lambda row: row["market_type"]),
        by_league=_bucket_rows(rows, lambda row: row["league"] or "Unknown"),
    )


@router.get("/signals/performance/signals", response_model=list[SignalPerformanceRow])
def signal_performance_rows(
    db: Session = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[SignalPerformanceRow]:
    return [_signal_row(row) for row in _signal_result_rows(db, limit=limit)]


@router.get("/signals/performance/sweeps", response_model=list[BacktestSweepResultOut])
def signal_performance_sweeps(
    db: Session = Depends(get_db),
    latest_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[BacktestSweepResult]:
    stmt = select(BacktestSweepResult).order_by(BacktestSweepResult.created_at.desc()).limit(limit)
    rows = list(db.scalars(stmt))
    if not latest_only or not rows:
        return rows
    latest_run_id = rows[0].run_id
    return [row for row in rows if row.run_id == latest_run_id]


@router.get("/signals/performance/{market_id}", response_model=list[SignalPerformanceRow])
def signal_performance_for_market(
    market_id: str,
    db: Session = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[SignalPerformanceRow]:
    return [_signal_row(row) for row in _signal_result_rows(db, market_id=market_id, limit=limit)]


def _signal_result_rows(db: Session, market_id: str | None = None, limit: int | None = None) -> list[dict]:
    stmt = (
        select(PaperTradeSignal, SignalBacktestResult)
        .join(SignalBacktestResult, SignalBacktestResult.signal_id == PaperTradeSignal.id)
        .order_by(PaperTradeSignal.timestamp.desc(), SignalBacktestResult.horizon.asc())
    )
    if market_id:
        stmt = stmt.where(PaperTradeSignal.market_id == market_id)
    if limit:
        stmt = stmt.limit(limit)
    rows: list[dict] = []
    for signal, result in db.execute(stmt).all():
        signal_payload = signal.raw_payload if isinstance(signal.raw_payload, dict) else {}
        result_payload = result.raw_payload if isinstance(result.raw_payload, dict) else {}
        evaluation_status = result_payload.get("evaluation_status") or _evaluation_status(result)
        raw_outcome_side = signal_payload.get("raw_outcome_side") or signal_payload.get("raw_prediction_side")
        raw_historical_price = _float_or_none(signal_payload.get("raw_historical_price", signal_payload.get("historical_price")))
        derived_yes_probability = _derived_yes_from_payload(raw_outcome_side, raw_historical_price, signal.entry_market_yes_probability)
        suspicion_reason = _suspicion_reason(signal, signal_payload)
        invalid_entry_probability = not (
            _probability_in_range(signal.entry_market_yes_probability)
            and _probability_in_range(signal.entry_sportsbook_fair_probability)
            and -1 <= signal.entry_net_edge <= 1
        )
        if suspicion_reason:
            evaluation_status = "suspicious_probability_orientation"
        elif invalid_entry_probability:
            evaluation_status = "invalid_probability"
        signal_direction = result_payload.get("signal_direction")
        paper_side = result_payload.get("paper_side")
        if paper_side is None and result.paper_pnl_per_contract is not None:
            paper_side = "NO" if signal.direction == "possible_yes_overpricing" else "YES"
        entry_price = _float_or_none(result_payload.get("entry_price"))
        if entry_price is None and paper_side:
            entry_price = _paper_side_price(signal.entry_market_yes_probability, str(paper_side))
        exit_price = _float_or_none(result_payload.get("exit_price"))
        if exit_price is None and paper_side and result.exit_market_yes_probability is not None:
            exit_price = _paper_side_price(result.exit_market_yes_probability, str(paper_side))
        paper_pnl = result.paper_pnl_per_contract
        return_on_stake = result.return_on_stake
        if signal.direction == "possible_yes_overpricing" and paper_side == "NO" and result.exit_market_yes_probability is not None:
            paper_pnl = (1 - result.exit_market_yes_probability) - (1 - signal.entry_market_yes_probability)
            return_on_stake = paper_pnl / entry_price if entry_price and entry_price > 0 else None
        signal_category = _signal_category(signal.direction, evaluation_status, paper_pnl, paper_side)
        market_yes_change = _float_or_none(result_payload.get("market_yes_change"))
        if market_yes_change is None and result.exit_market_yes_probability is not None:
            market_yes_change = result.exit_market_yes_probability - signal.entry_market_yes_probability
        sportsbook_fair_change = _float_or_none(result_payload.get("sportsbook_fair_change"))
        if sportsbook_fair_change is None and result.exit_sportsbook_fair_probability is not None:
            sportsbook_fair_change = result.exit_sportsbook_fair_probability - signal.entry_sportsbook_fair_probability
        absolute_edge_change = _float_or_none(result_payload.get("absolute_edge_change"))
        if absolute_edge_change is None and result.exit_net_edge is not None:
            absolute_edge_change = abs(result.exit_net_edge) - abs(signal.entry_net_edge)
        closure_reason = result_payload.get("closure_reason")
        if not closure_reason and result.exit_market_yes_probability is not None and result.exit_sportsbook_fair_probability is not None:
            closure_reason = classify_closure_reason(
                entry_market_yes=signal.entry_market_yes_probability,
                entry_sportsbook_fair=signal.entry_sportsbook_fair_probability,
                exit_market_yes=result.exit_market_yes_probability,
                exit_sportsbook_fair=result.exit_sportsbook_fair_probability,
                signal_direction="negative_edge_no_side" if paper_side == "NO" else "positive_edge_long_yes",
            )
        rows.append(
            {
                "signal_id": signal.id,
                "market_id": signal.market_id,
                "timestamp": signal.timestamp,
                "title": signal.title,
                "display_outcome": signal.display_outcome,
                "market_type": signal.market_type,
                "league": signal.league,
                "direction": signal.direction,
                "signal_direction": signal_direction or ("negative_edge_no_side" if paper_side == "NO" else "positive_edge_long_yes" if paper_side == "YES" else None),
                "paper_side": paper_side,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "entry_market_yes_probability": signal.entry_market_yes_probability,
                "entry_sportsbook_fair_probability": signal.entry_sportsbook_fair_probability,
                "entry_net_edge": None if invalid_entry_probability or suspicion_reason else signal.entry_net_edge,
                "confidence_score": signal.confidence_score,
                "horizon": result.horizon,
                "exit_market_yes_probability": result.exit_market_yes_probability,
                "exit_sportsbook_fair_probability": result.exit_sportsbook_fair_probability,
                "exit_net_edge": result.exit_net_edge,
                "market_yes_change": market_yes_change,
                "sportsbook_fair_change": sportsbook_fair_change,
                "edge_change": result.edge_change,
                "absolute_edge_change": absolute_edge_change,
                "closure_reason": closure_reason,
                "paper_pnl_per_contract": paper_pnl,
                "return_on_stake": return_on_stake,
                "did_edge_close": result.did_edge_close,
                "moved_expected_direction": result.moved_expected_direction,
                "skip_reason": (
                    "suspicious_probability_orientation"
                    if suspicion_reason
                    else ("invalid_probability_range" if invalid_entry_probability else result.skip_reason)
                ),
                "evaluation_status": evaluation_status,
                "signal_category": signal_category,
                "raw_outcome_side": raw_outcome_side,
                "raw_historical_price": raw_historical_price,
                "derived_market_yes_probability": derived_yes_probability,
                "suspicion_reason": suspicion_reason,
                "liquidity_status": signal_payload.get("liquidity_status"),
                "liquidity_adjusted": signal_payload.get("liquidity_adjusted"),
            }
        )
    return rows


def _signal_row(row: dict) -> SignalPerformanceRow:
    return SignalPerformanceRow(**row)


def _bucket_rows(rows: list[dict], key_fn) -> list[SignalPerformanceBucket]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(str(key_fn(row)), []).append(row)
    return [SignalPerformanceBucket(key=key, **_aggregate_rows(values)) for key, values in sorted(buckets.items())]


def _aggregate_rows(rows: list[dict]) -> dict:
    signal_ids = {row["signal_id"] for row in rows}
    suspicious_ids = {
        row["signal_id"]
        for row in rows
        if row.get("signal_category") == "suspicious_or_invalid"
    }
    usable_rows = [row for row in rows if row["signal_id"] not in suspicious_ids]
    usable_signal_ids = signal_ids - suspicious_ids
    simulated_long_yes_ids = {
        row["signal_id"]
        for row in usable_rows
        if row.get("signal_category") in {"positive_edge_long_yes_simulated", "unevaluated_missing_future_price"}
    }
    evaluated_long_yes_ids = {
        row["signal_id"]
        for row in usable_rows
        if row.get("signal_category") == "positive_edge_long_yes_simulated" and row["paper_pnl_per_contract"] is not None
    }
    simulated_negative_ids = {
        row["signal_id"]
        for row in usable_rows
        if row.get("signal_category") in {"negative_edge_no_side_simulated", "unevaluated_negative_edge_no_side"}
    }
    evaluated_negative_ids = {
        row["signal_id"]
        for row in usable_rows
        if row.get("signal_category") == "negative_edge_no_side_simulated" and row["paper_pnl_per_contract"] is not None
    }
    evaluated_signal_ids = evaluated_long_yes_ids | evaluated_negative_ids
    tracked_negative_ids = {
        row["signal_id"]
        for row in usable_rows
        if row.get("signal_category") == "negative_edge_overpricing_tracked_only"
    }
    invalid_signal_ids = {
        row["signal_id"]
        for row in rows
        if row.get("evaluation_status") in {"invalid_probability", "suspicious_probability_orientation"}
        or row.get("skip_reason") in {"invalid_probability_range", "suspicious_probability_orientation"}
    }
    evaluated = [
        row
        for row in usable_rows
        if row.get("signal_category") in {"positive_edge_long_yes_simulated", "negative_edge_no_side_simulated"}
        and row["paper_pnl_per_contract"] is not None
    ]
    evaluated_yes = [
        row
        for row in evaluated
        if row.get("paper_side") == "YES"
    ]
    evaluated_no = [
        row
        for row in evaluated
        if row.get("paper_side") == "NO"
    ]
    edge_closed = [row for row in evaluated if row["did_edge_close"] is not None]
    directional = [row for row in evaluated if row["moved_expected_direction"] is not None]
    attribution = _attribution_metrics(evaluated)
    return {
        "total_signals": len(usable_signal_ids),
        "evaluated_signals": len(evaluated_signal_ids),
        "simulated_long_yes_signals": len(simulated_long_yes_ids),
        "evaluated_long_yes_signals": len(evaluated_long_yes_ids),
        "tracked_negative_edge_signals": len(tracked_negative_ids),
        "simulated_negative_edge_signals": len(simulated_negative_ids),
        "evaluated_negative_edge_signals": len(evaluated_negative_ids),
        "unevaluated_signals": len((simulated_long_yes_ids | simulated_negative_ids) - evaluated_signal_ids),
        "suspicious_invalid_signals": len(suspicious_ids | invalid_signal_ids),
        "skipped_invalid_signals": len(invalid_signal_ids),
        "average_entry_edge": _avg([row["entry_net_edge"] for row in usable_rows]),
        "average_paper_pnl_per_contract": _avg([row["paper_pnl_per_contract"] for row in evaluated]),
        "average_return_on_stake": _avg([row["return_on_stake"] for row in evaluated]),
        "yes_side_average_paper_pnl_per_contract": _avg([row["paper_pnl_per_contract"] for row in evaluated_yes]),
        "yes_side_average_return_on_stake": _avg([row["return_on_stake"] for row in evaluated_yes]),
        "no_side_average_paper_pnl_per_contract": _avg([row["paper_pnl_per_contract"] for row in evaluated_no]),
        "no_side_average_return_on_stake": _avg([row["return_on_stake"] for row in evaluated_no]),
        "edge_close_rate": _rate([row["did_edge_close"] for row in edge_closed]),
        "directional_accuracy": _rate([row["moved_expected_direction"] for row in directional]),
        **attribution,
        "contains_unadjusted_liquidity": any(row.get("liquidity_adjusted") is False for row in rows),
    }


def _attribution_metrics(rows: list[dict]) -> dict:
    classified = [row for row in rows if row.get("closure_reason")]
    denominator = len(classified)

    def reason_rate(reason: str) -> float | None:
        if denominator == 0:
            return None
        return sum(1 for row in classified if row.get("closure_reason") == reason) / denominator

    return {
        "market_driven_close_rate": reason_rate("market_moved_expected_direction"),
        "fair_value_driven_close_rate": reason_rate("fair_moved_toward_market"),
        "both_moved_close_rate": reason_rate("both_moved_toward_each_other"),
        "edge_widened_rate": reason_rate("edge_widened"),
        "no_meaningful_change_rate": reason_rate("no_meaningful_change"),
        "average_market_yes_change": _avg([row.get("market_yes_change") for row in classified]),
        "average_sportsbook_fair_change": _avg([row.get("sportsbook_fair_change") for row in classified]),
        "average_edge_change": _avg([row.get("edge_change") for row in classified]),
        "average_absolute_edge_change": _avg([row.get("absolute_edge_change") for row in classified]),
    }


def _avg(values: list[float | None]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return sum(numbers) / len(numbers) if numbers else None


def _rate(values: list[bool | None]) -> float | None:
    booleans = [bool(value) for value in values if value is not None]
    return sum(1 for value in booleans if value) / len(booleans) if booleans else None


def _confidence_bucket(value: float) -> str:
    if value >= 0.95:
        return "0.95+"
    if value >= 0.90:
        return "0.90-0.95"
    if value >= 0.85:
        return "0.85-0.90"
    return "<0.85"


def _probability_in_range(value: float | None) -> bool:
    return value is not None and 0 <= value <= 1


def _suspicion_reason(signal: PaperTradeSignal, payload: dict) -> str | None:
    if abs(signal.entry_net_edge) > 0.50:
        return "Net edge magnitude exceeded 50%, which usually indicates YES/NO orientation mismatch or stale data."
    raw_side = str(payload.get("raw_outcome_side") or payload.get("raw_prediction_side") or "").lower()
    raw_price = payload.get("raw_historical_price", payload.get("historical_price"))
    try:
        raw_price_float = float(raw_price) if raw_price is not None else None
    except (TypeError, ValueError):
        raw_price_float = None
    if signal.market_type in {"futures", "awards", "outrights"} and signal.entry_market_yes_probability > 0.95:
        title = signal.title.lower()
        championship_text = any(term in title for term in ("finals", "stanley cup", "world cup", "championship", "win the"))
        raw_no_leak = raw_side == "no" and raw_price_float is not None and raw_price_float > 0.95
        if championship_text or raw_no_leak:
            return "Futures/awards Market YES probability is above 95% for a likely longshot-style market."
    return None


def _derived_yes_from_payload(raw_side: str | None, raw_price: object, fallback: float) -> float:
    try:
        price = float(raw_price) if raw_price is not None else fallback
    except (TypeError, ValueError):
        price = fallback
    if (raw_side or "").lower() == "no":
        return 1 - price
    return price


def _float_or_none(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _signal_category(direction: str, evaluation_status: str, pnl: float | None, paper_side: object = None) -> str:
    if evaluation_status in {"suspicious_probability_orientation", "invalid_probability"}:
        return "suspicious_or_invalid"
    if direction == "possible_yes_overpricing":
        if str(paper_side or "").upper() == "NO":
            return "negative_edge_no_side_simulated" if pnl is not None else "unevaluated_negative_edge_no_side"
        return "negative_edge_overpricing_tracked_only"
    if direction == "possible_yes_underpricing":
        return "positive_edge_long_yes_simulated" if pnl is not None else "unevaluated_missing_future_price"
    return "unevaluated_missing_future_price"


def _evaluation_status(result: SignalBacktestResult) -> str:
    if result.paper_pnl_per_contract is not None:
        return "evaluated" if result.exit_sportsbook_fair_probability is not None else "missing_future_fair"
    if result.skip_reason == "missing_future_price" or result.skip_reason == "no_historical_polymarket_price":
        return "missing_future_price"
    if result.skip_reason == "invalid_probability_range":
        return "invalid_probability"
    if result.skip_reason in {"negative_edge_no_long_simulation", "negative_edge_no_default_paper_trade"}:
        return "negative_edge_no_long_simulation"
    return result.skip_reason or "unevaluated"


def _paper_side_price(market_yes_probability: float, paper_side: str) -> float:
    return 1 - market_yes_probability if paper_side.upper() == "NO" else market_yes_probability


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
