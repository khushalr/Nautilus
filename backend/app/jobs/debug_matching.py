from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime

from sqlalchemy import desc, select

from app.core.db import SessionLocal
from app.jobs.compute_fair_values import possible_outright_matches
from app.models import Market, SportsbookEvent, SportsbookOddsSnapshot
from app.services.market_classification import effective_prediction_market_type
from app.services.normalization import infer_market_league, possible_event_matches


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect prediction-market to sportsbook matching inputs.")
    parser.add_argument("--limit", type=int, default=10, help="Number of sample markets/events to print.")
    parser.add_argument("--matches", type=int, default=3, help="Number of fuzzy candidate matches per market.")
    args = parser.parse_args()

    with SessionLocal() as db:
        markets = list(
            db.scalars(
                select(Market)
                .where(Market.status == "open")
                .order_by(Market.start_time.asc().nulls_last(), Market.event_name.asc())
                .limit(args.limit)
            )
        )
        events = list(
            db.scalars(
                select(SportsbookEvent)
                .order_by(SportsbookEvent.start_time.asc().nulls_last(), SportsbookEvent.event_name.asc())
                .limit(max(args.limit, 50))
            )
        )
        all_events = list(db.scalars(select(SportsbookEvent)))
        h2h_events = list(
            db.scalars(
                select(SportsbookEvent)
                .join(SportsbookOddsSnapshot)
                .where(SportsbookOddsSnapshot.market_type.in_(("h2h", "moneyline")))
                .distinct()
            )
        )
        all_markets = list(db.scalars(select(Market).where(Market.status == "open")))
        outright_snapshots = list(
            db.scalars(
                select(SportsbookOddsSnapshot)
                .where(SportsbookOddsSnapshot.market_type == "outrights")
                .order_by(desc(SportsbookOddsSnapshot.observed_at))
                .limit(8000)
            )
        )
        h2h_markets = [
            market
            for market in all_markets
            if effective_prediction_market_type(market) == "h2h"
        ][: args.limit]
        outright_markets = [
            market
            for market in all_markets
            if effective_prediction_market_type(market) in {"futures", "awards"}
        ][: args.limit]
        outright_debug = {
            market.id: possible_outright_matches(
                market,
                outright_snapshots,
                market_type=effective_prediction_market_type(market),
                limit=args.matches,
            )
            for market in outright_markets
        }
        sportsbook_samples = [
            {
                "bookmaker": sample.bookmaker,
                "selection": sample.selection,
                "american_odds": sample.american_odds,
                "decimal_odds": sample.decimal_odds,
                "implied_probability": sample.implied_probability,
                "event_name": sample.event.event_name if sample.event else sample.event_id,
            }
            for sample in db.scalars(
                select(SportsbookOddsSnapshot)
                .where(SportsbookOddsSnapshot.market_type == "outrights")
                .order_by(desc(SportsbookOddsSnapshot.observed_at))
                .limit(12)
            )
        ]
        sportsbook_market_types = Counter(
            db.scalars(select(SportsbookOddsSnapshot.market_type)).all()
        )

    _print_collection_debug(all_markets)
    _print_sportsbook_debug(sportsbook_market_types, sportsbook_samples)

    print("\nPrediction markets")
    print("------------------")
    for market in markets:
        print(
            " | ".join(
                [
                    f"title={market.event_name}",
                    f"source={market.source}",
                    f"sport={infer_market_league(market)}",
                    f"league={market.league}",
                    f"key={market.normalized_event_key}",
                    f"start={_format_time(market.start_time)}",
                ]
            )
        )

    print("\nSportsbook events")
    print("-----------------")
    for event in events[: args.limit]:
        print(
            " | ".join(
                [
                    f"event={event.event_name}",
                    f"teams={event.away_team} at {event.home_team}",
                    f"league={event.league}",
                    f"key={event.normalized_event_key}",
                    f"start={_format_time(event.start_time)}",
                ]
            )
        )

    print("\nH2H possible matches")
    print("--------------------")
    if not h2h_markets:
        print("No H2H prediction markets available in the sample.")
    for market in h2h_markets:
        print(f"\n{market.event_name} [{market.source}] key={market.normalized_event_key}")
        candidates = possible_event_matches(market, h2h_events, limit=args.matches)
        if not candidates:
            print("  no sportsbook h2h/moneyline events available")
            continue
        for match in candidates:
            event = match.event
            print(
                "  "
                + " | ".join(
                    [
                        f"score={match.confidence_score:.3f}",
                        f"type={match.match_type}",
                        f"event={event.event_name}",
                        f"league={event.league}",
                        f"key={match.normalized_event_key}",
                        f"team={match.team_score:.3f}",
                        f"date={match.date_score:.3f}",
                        f"fuzzy={match.fuzzy_score:.3f}",
                    ]
                )
        )

    print("\nFutures/outrights possible matches")
    print("----------------------------------")
    if not outright_markets:
        print("No futures/awards prediction markets available in the sample.")
    for market in outright_markets:
        print(f"\n{market.event_name} [{market.source}]")
        for candidate in outright_debug.get(market.id, []):
            print(
                "  "
                + " | ".join(
                    [
                        f"target={candidate.target_outcome}",
                        f"context={candidate.market_context}",
                        f"event={candidate.sportsbook_event}",
                        f"selection={candidate.sportsbook_selection}",
                        f"confidence={candidate.confidence_score:.3f}",
                        f"reason={candidate.reason}",
                    ]
                )
            )


def _print_collection_debug(markets: list[Market]) -> None:
    by_type = Counter(effective_prediction_market_type(market) for market in markets)
    by_league = Counter(market.league or "unknown" for market in markets)
    missing_start_time = sum(1 for market in markets if market.start_time is None)
    skipped_samples = [
        market.event_name
        for market in markets
        if effective_prediction_market_type(market) in {"futures", "awards"}
    ][:8]

    print("\nPrediction-market collection debug")
    print("----------------------------------")
    print(f"markets_by_market_type={dict(sorted(by_type.items()))}")
    print(f"markets_by_league={dict(by_league.most_common(20))}")
    print(f"markets_missing_start_time={missing_start_time}")
    if skipped_samples:
        print("sample_skipped_futures_awards=")
        for title in skipped_samples:
            print(f"  - {title}")


def _print_sportsbook_debug(
    market_types: Counter,
    outright_samples: list[dict],
) -> None:
    print("\nSportsbook collection debug")
    print("---------------------------")
    print(f"sportsbook_market_types={dict(sorted(market_types.items()))}")
    if not market_types.get("outrights"):
        print(
            "no_sportsbook_futures_awards_odds=The Odds API returned no outrights snapshots. "
            "Outrights are available only for selected sports/competitions and may be absent for "
            "the configured plan, regions, or sports."
        )
        return
    print("sample_futures_awards_odds=")
    for sample in outright_samples:
        print(
            "  "
            + " | ".join(
                [
                    f"book={sample['bookmaker']}",
                    f"selection={sample['selection']}",
                    f"american={sample['american_odds']}",
                    f"decimal={sample['decimal_odds']}",
                    f"implied={sample['implied_probability']:.4f}",
                    f"event={sample['event_name']}",
                ]
            )
        )


def _format_time(value: datetime | None) -> str:
    return value.isoformat() if value else "None"


if __name__ == "__main__":
    main()
