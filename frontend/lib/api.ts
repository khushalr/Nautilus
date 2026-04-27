import type { AlertRule, MarketDetail, Opportunity, UserModel } from "@/types/api";

const serverApiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const clientApiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchJson<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${serverApiUrl}${path}`, { next: { revalidate: 20 } });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function getOpportunities(): Promise<Opportunity[]> {
  return (await fetchJson<Opportunity[]>("/opportunities?min_net_edge=-1&limit=100")) ?? sampleOpportunities;
}

export async function getMarketDetail(id: string): Promise<MarketDetail> {
  return (await fetchJson<MarketDetail>(`/markets/${id}`)) ?? sampleMarketDetail(id);
}

export async function getUserModels(): Promise<UserModel[]> {
  return (await fetchJson<UserModel[]>("/user-models")) ?? sampleUserModels;
}

export async function getAlerts(): Promise<AlertRule[]> {
  return (await fetchJson<AlertRule[]>("/alerts")) ?? sampleAlerts;
}

export function apiUrl(path: string): string {
  return `${clientApiUrl}${path}`;
}

const now = new Date("2026-04-26T18:00:00Z").toISOString();

export const sampleOpportunities: Opportunity[] = [
  {
    market: {
      id: "sample-chiefs",
      source: "polymarket",
      external_id: "sample-chiefs",
      event_name: "Kansas City Chiefs at Buffalo Bills",
      league: "NFL",
      market_type: "moneyline",
      selection: "Kansas City Chiefs",
      normalized_event_key: "nfl:2026-09-14:buf-vs-kc",
      start_time: "2026-09-14T00:20:00Z",
      status: "open",
      market_url: null,
      extra: {}
    },
    fair_value: {
      id: "fv-chiefs",
      market_id: "sample-chiefs",
      fair_probability: 0.548,
      market_probability: 0.505,
      gross_edge: 0.043,
      net_edge: 0.031,
      spread: 0.018,
      liquidity: 18400,
      confidence_score: 0.82,
      sportsbook_consensus: { books: 6 },
      assumptions: {},
      explanation_json: {},
      explanation: "Consensus sportsbook price after removing two-way vig.",
      observed_at: now
    }
  },
  {
    market: {
      id: "sample-celtics",
      source: "kalshi",
      external_id: "sample-celtics",
      event_name: "Boston Celtics vs New York Knicks",
      league: "NBA",
      market_type: "moneyline",
      selection: "Boston Celtics",
      normalized_event_key: "nba:2026-05-03:bos-vs-nyk",
      start_time: "2026-05-03T23:00:00Z",
      status: "open",
      market_url: null,
      extra: {}
    },
    fair_value: {
      id: "fv-celtics",
      market_id: "sample-celtics",
      fair_probability: 0.612,
      market_probability: 0.586,
      gross_edge: 0.026,
      net_edge: 0.018,
      spread: 0.012,
      liquidity: 9200,
      confidence_score: 0.76,
      sportsbook_consensus: { books: 5 },
      assumptions: {},
      explanation_json: {},
      explanation: "Consensus sportsbook price after removing two-way vig.",
      observed_at: now
    }
  },
  {
    market: {
      id: "sample-dodgers",
      source: "polymarket",
      external_id: "sample-dodgers",
      event_name: "Los Angeles Dodgers at San Diego Padres",
      league: "MLB",
      market_type: "moneyline",
      selection: "San Diego Padres",
      normalized_event_key: "mlb:2026-04-27:lad-vs-sd",
      start_time: "2026-04-27T02:10:00Z",
      status: "open",
      market_url: null,
      extra: {}
    },
    fair_value: {
      id: "fv-padres",
      market_id: "sample-dodgers",
      fair_probability: 0.471,
      market_probability: 0.462,
      gross_edge: 0.009,
      net_edge: 0.002,
      spread: 0.01,
      liquidity: 2400,
      confidence_score: 0.61,
      sportsbook_consensus: { books: 4 },
      assumptions: {},
      explanation_json: {},
      explanation: "Consensus sportsbook price after removing two-way vig.",
      observed_at: now
    }
  }
];

export function sampleMarketDetail(id: string): MarketDetail {
  const opportunity = sampleOpportunities.find((item) => item.market.id === id) ?? sampleOpportunities[0];
  const baseTime = Date.parse("2026-04-26T14:00:00Z");
  const prediction_snapshots = Array.from({ length: 18 }, (_, index) => {
    const marketProbability = opportunity.fair_value.market_probability + Math.sin(index / 2) * 0.01 - 0.012 + index * 0.001;
    return {
      id: `pm-${index}`,
      market_id: opportunity.market.id,
      source: opportunity.market.source,
      bid_probability: marketProbability - 0.009,
      ask_probability: marketProbability + 0.009,
      last_price: marketProbability,
      midpoint_probability: marketProbability,
      spread: 0.018,
      liquidity: 12000 + index * 370,
      volume: 42000 + index * 900,
      observed_at: new Date(baseTime + index * 20 * 60 * 1000).toISOString()
    };
  });
  const fair_value_history = prediction_snapshots.map((snapshot, index) => ({
    ...opportunity.fair_value,
    id: `fv-${index}`,
    market_probability: snapshot.midpoint_probability,
    fair_probability: opportunity.fair_value.fair_probability + Math.cos(index / 3) * 0.006,
    gross_edge: opportunity.fair_value.fair_probability - snapshot.midpoint_probability,
    net_edge: opportunity.fair_value.fair_probability - snapshot.midpoint_probability - 0.012,
    observed_at: snapshot.observed_at
  }));
  return {
    market: opportunity.market,
    latest_fair_value: opportunity.fair_value,
    prediction_snapshots,
    fair_value_history,
    sportsbook_odds: [
      {
        id: "dk",
        bookmaker: "draftkings",
        market_type: "moneyline",
        selection: opportunity.market.selection,
        american_odds: -118,
        decimal_odds: 1.85,
        implied_probability: 0.541,
        observed_at: now
      },
      {
        id: "fd",
        bookmaker: "fanduel",
        market_type: "moneyline",
        selection: opportunity.market.selection,
        american_odds: -122,
        decimal_odds: 1.82,
        implied_probability: 0.55,
        observed_at: now
      },
      {
        id: "pin",
        bookmaker: "pinnacle",
        market_type: "moneyline",
        selection: opportunity.market.selection,
        american_odds: -115,
        decimal_odds: 1.87,
        implied_probability: 0.535,
        observed_at: now
      }
    ]
  };
}

export const sampleUserModels: UserModel[] = [
  {
    id: "default",
    name: "Default Research Model",
    config: {
      min_edge: 0.03,
      max_spread: 0.06,
      min_liquidity: 500,
      spread_penalty_multiplier: 0.5,
      bookmaker_weights: { draftkings: 1, fanduel: 1, pinnacle: 1.2 },
      excluded_bookmakers: []
    },
    created_at: now,
    updated_at: now
  }
];

export const sampleAlerts: AlertRule[] = [
  {
    id: "alert-sample",
    user_id: "default",
    name: "High confidence edges",
    min_net_edge: 0.025,
    max_spread: 0.04,
    min_liquidity: 500,
    league: null,
    source: null,
    delivery_channel: "discord",
    delivery_target: "https://discord.com/api/webhooks/example",
    is_active: true,
    created_at: now,
    updated_at: now
  }
];
