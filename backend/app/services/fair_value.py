from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev


DEFAULT_MAX_LIQUIDITY_PENALTY = 0.10


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def american_to_probability(odds: int | float) -> float:
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def decimal_to_probability(odds: float) -> float:
    if odds <= 1:
        raise ValueError("Decimal odds must be greater than 1")
    return 1 / odds


def remove_vig_two_way(probability_a: float, probability_b: float) -> tuple[float, float]:
    total = probability_a + probability_b
    if total <= 0:
        raise ValueError("At least one side must have positive implied probability")
    return probability_a / total, probability_b / total


def consensus_fair_probability(probabilities: list[float]) -> float:
    clean = [p for p in probabilities if 0 < p < 1]
    if not clean:
        raise ValueError("No valid probabilities supplied")
    return mean(clean)


def weighted_consensus_fair_probability(probabilities: list[float], weights: list[float]) -> float:
    clean_pairs = [(p, w) for p, w in zip(probabilities, weights, strict=False) if 0 < p < 1 and w > 0]
    if not clean_pairs:
        raise ValueError("No valid weighted probabilities supplied")
    total_weight = sum(weight for _, weight in clean_pairs)
    return sum(probability * weight for probability, weight in clean_pairs) / total_weight


def consensus_dispersion(probabilities: list[float]) -> float:
    clean = [p for p in probabilities if 0 < p < 1]
    if len(clean) <= 1:
        return 0.0
    return pstdev(clean)


def calculate_market_midpoint(
    bid_probability: float | None,
    ask_probability: float | None,
    last_probability: float | None = None,
) -> float:
    if bid_probability is not None and ask_probability is not None:
        return _clamp((bid_probability + ask_probability) / 2)
    if last_probability is not None:
        return _clamp(last_probability)
    if bid_probability is not None:
        return _clamp(bid_probability)
    if ask_probability is not None:
        return _clamp(ask_probability)
    raise ValueError("At least one probability input is required")


def market_probability_with_source(
    bid_probability: float | None,
    ask_probability: float | None,
    last_price: float | None = None,
) -> tuple[float, str]:
    if bid_probability is not None and ask_probability is not None:
        return _clamp((bid_probability + ask_probability) / 2), "midpoint"
    if last_price is not None:
        return _clamp(last_price), "last_price"
    raise ValueError("Market probability requires bid/ask midpoint or last_price")


def calculate_spread(bid_probability: float | None, ask_probability: float | None) -> float | None:
    if bid_probability is None or ask_probability is None:
        return None
    return max(0.0, ask_probability - bid_probability)


def calculate_gross_edge(fair_probability: float, market_probability: float) -> float:
    return fair_probability - market_probability


def calculate_spread_penalty(
    spread: float | None,
    multiplier: float = 0.5,
    max_penalty: float = 0.10,
) -> float:
    if spread is None or spread <= 0:
        return 0.0
    return max(0.0, min(max_penalty, spread * multiplier))


def calculate_liquidity_penalty(
    liquidity: float | None,
    min_liquidity: float = 500,
    multiplier: float = 0.02,
    max_penalty: float = 0.10,
) -> float:
    if liquidity is None:
        return max_penalty
    if liquidity >= min_liquidity:
        return 0.0
    shortfall = (min_liquidity - max(liquidity, 0)) / max(min_liquidity, 1)
    return _clamp(shortfall * multiplier, 0.0, max_penalty)


def calculate_net_edge(
    gross_edge: float,
    spread_penalty: float,
    liquidity_penalty: float,
) -> float:
    return gross_edge - spread_penalty - liquidity_penalty


def confidence_score(
    *,
    sportsbook_count: int,
    spread: float | None,
    liquidity: float | None,
    consensus_dispersion: float = 0.0,
    min_liquidity: float = 500,
) -> float:
    book_component = _clamp(sportsbook_count / 6)
    spread_component = 1 - _clamp((spread or 0) / 0.12)
    liquidity_component = _clamp((liquidity or 0) / max(min_liquidity, 1))
    dispersion_component = 1 - _clamp(consensus_dispersion / 0.08)
    return _clamp(
        (0.35 * book_component)
        + (0.25 * spread_component)
        + (0.25 * liquidity_component)
        + (0.15 * dispersion_component)
    )


@dataclass(frozen=True)
class FairValueResult:
    fair_probability: float
    market_probability: float
    market_probability_source: str
    gross_edge: float
    net_edge: float
    spread: float | None
    spread_penalty: float
    liquidity_penalty: float
    confidence_score: float


def evaluate_market(
    *,
    fair_probability: float,
    market_probability: float,
    spread: float | None,
    liquidity: float | None,
    sportsbook_count: int,
    consensus_dispersion: float,
    market_probability_source: str = "midpoint",
    min_liquidity: float = 500,
    spread_penalty_multiplier: float = 0.5,
    liquidity_penalty_multiplier: float = 0.02,
) -> FairValueResult:
    gross_edge = calculate_gross_edge(fair_probability, market_probability)
    spread_penalty = calculate_spread_penalty(spread, spread_penalty_multiplier)
    liquidity_penalty = calculate_liquidity_penalty(liquidity, min_liquidity, liquidity_penalty_multiplier)
    net_edge = calculate_net_edge(gross_edge, spread_penalty, liquidity_penalty)
    score = confidence_score(
        sportsbook_count=sportsbook_count,
        spread=spread,
        liquidity=liquidity,
        consensus_dispersion=consensus_dispersion,
        min_liquidity=min_liquidity,
    )
    return FairValueResult(
        fair_probability=fair_probability,
        market_probability=market_probability,
        market_probability_source=market_probability_source,
        gross_edge=gross_edge,
        net_edge=net_edge,
        spread=spread,
        spread_penalty=spread_penalty,
        liquidity_penalty=liquidity_penalty,
        confidence_score=score,
    )


@dataclass(frozen=True)
class EdgeInputs:
    fair_probability: float
    bid_probability: float | None
    ask_probability: float | None
    last_price: float | None
    liquidity: float | None
    sportsbook_count: int
    consensus_dispersion: float
    min_liquidity: float = 500
    spread_penalty_multiplier: float = 0.5
    liquidity_penalty_multiplier: float = 0.02
    max_liquidity_penalty: float = DEFAULT_MAX_LIQUIDITY_PENALTY


def calculate_edge(inputs: EdgeInputs) -> FairValueResult:
    market_probability, source = market_probability_with_source(
        inputs.bid_probability,
        inputs.ask_probability,
        inputs.last_price,
    )
    spread = calculate_spread(inputs.bid_probability, inputs.ask_probability)
    gross_edge = calculate_gross_edge(inputs.fair_probability, market_probability)
    spread_penalty = calculate_spread_penalty(spread, inputs.spread_penalty_multiplier)
    liquidity_penalty = calculate_liquidity_penalty(
        inputs.liquidity,
        inputs.min_liquidity,
        inputs.liquidity_penalty_multiplier,
        inputs.max_liquidity_penalty,
    )
    net_edge = calculate_net_edge(gross_edge, spread_penalty, liquidity_penalty)
    score = confidence_score(
        sportsbook_count=inputs.sportsbook_count,
        spread=spread,
        liquidity=inputs.liquidity,
        consensus_dispersion=inputs.consensus_dispersion,
        min_liquidity=inputs.min_liquidity,
    )
    return FairValueResult(
        fair_probability=inputs.fair_probability,
        market_probability=market_probability,
        market_probability_source=source,
        gross_edge=gross_edge,
        net_edge=net_edge,
        spread=spread,
        spread_penalty=spread_penalty,
        liquidity_penalty=liquidity_penalty,
        confidence_score=score,
    )
