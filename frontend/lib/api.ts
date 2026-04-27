import type { AlertRule, MarketDetail, Opportunity, OpportunityHistoryRow, UserModel } from "@/types/api";

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
    market_id: "sample-chiefs",
    title: "Kansas City Chiefs at Buffalo Bills",
    source: "polymarket",
    external_id: "sample-chiefs",
    league: "NFL",
    market_type: "moneyline",
    outcome: "Kansas City Chiefs",
    display_outcome: "Kansas City Chiefs",
    start_time: "2026-09-14T00:20:00Z",
    status: "open",
    market_url: null,
    market_probability: 0.505,
    fair_probability: 0.548,
    gross_edge: 0.043,
    net_edge: 0.031,
    spread: 0.018,
    liquidity: 18400,
    confidence_score: 0.82,
    matched_sportsbook_category: "Kansas City Chiefs at Buffalo Bills",
    matched_selection: "Kansas City Chiefs",
    match_confidence: 0.9,
    sportsbooks_used: ["draftkings", "fanduel", "pinnacle"],
    last_updated: now
  },
  {
    market_id: "sample-celtics",
    title: "Boston Celtics vs New York Knicks",
    source: "kalshi",
    external_id: "sample-celtics",
    league: "NBA",
    market_type: "moneyline",
    outcome: "Boston Celtics",
    display_outcome: "Boston Celtics",
    start_time: "2026-05-03T23:00:00Z",
    status: "open",
    market_url: null,
    market_probability: 0.586,
    fair_probability: 0.612,
    gross_edge: 0.026,
    net_edge: 0.018,
    spread: 0.012,
    liquidity: 9200,
    confidence_score: 0.76,
    matched_sportsbook_category: "Boston Celtics vs New York Knicks",
    matched_selection: "Boston Celtics",
    match_confidence: 0.86,
    sportsbooks_used: ["draftkings", "fanduel"],
    last_updated: now
  },
  {
    market_id: "sample-dodgers",
    title: "Los Angeles Dodgers at San Diego Padres",
    source: "polymarket",
    external_id: "sample-dodgers",
    league: "MLB",
    market_type: "moneyline",
    outcome: "San Diego Padres",
    display_outcome: "San Diego Padres",
    start_time: "2026-04-27T02:10:00Z",
    status: "open",
    market_url: null,
    market_probability: 0.462,
    fair_probability: 0.471,
    gross_edge: 0.009,
    net_edge: 0.002,
    spread: 0.01,
    liquidity: 2400,
    confidence_score: 0.61,
    matched_sportsbook_category: "Los Angeles Dodgers at San Diego Padres",
    matched_selection: "San Diego Padres",
    match_confidence: 0.75,
    sportsbooks_used: ["draftkings"],
    last_updated: now
  }
];

export function sampleMarketDetail(id: string): MarketDetail {
  const opportunity = sampleOpportunities.find((item) => item.market_id === id) ?? sampleOpportunities[0];
  const market = {
    id: opportunity.market_id,
    source: opportunity.source,
    external_id: opportunity.external_id,
    event_name: opportunity.title,
    league: opportunity.league,
    market_type: opportunity.market_type,
    selection: opportunity.display_outcome ?? opportunity.outcome ?? "Yes",
    normalized_event_key: `${opportunity.league ?? "sample"}:${opportunity.market_id}`,
    start_time: opportunity.start_time,
    status: opportunity.status,
    market_url: opportunity.market_url,
    extra: {}
  };
  const fairValue = {
    id: `fv-${opportunity.market_id}`,
    market_id: opportunity.market_id,
    fair_probability: opportunity.fair_probability,
    market_probability: opportunity.market_probability,
    gross_edge: opportunity.gross_edge,
    net_edge: opportunity.net_edge,
    spread: opportunity.spread,
    liquidity: opportunity.liquidity,
    confidence_score: opportunity.confidence_score,
    sportsbook_consensus: { books: opportunity.sportsbooks_used.length },
    assumptions: {},
    explanation_json: {
      selected_bookmakers: opportunity.sportsbooks_used,
      market: { display_outcome: opportunity.display_outcome, selection: market.selection },
      market_probability: { value: opportunity.market_probability, source: "sample", display_outcome: opportunity.display_outcome },
      matched_event: {
        event_name: opportunity.matched_sportsbook_category,
        confidence_score: opportunity.match_confidence,
        reason: "Bundled sample match."
      }
    },
    explanation: "Consensus sportsbook price after removing vig.",
    observed_at: opportunity.last_updated
  };
  const baseTime = Date.parse("2026-04-26T14:00:00Z");
  const prediction_snapshots = Array.from({ length: 18 }, (_, index) => {
    const marketProbability = opportunity.market_probability + Math.sin(index / 2) * 0.01 - 0.012 + index * 0.001;
    return {
      id: `pm-${index}`,
      market_id: market.id,
      source: market.source,
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
    ...fairValue,
    id: `fv-${index}`,
    market_probability: snapshot.midpoint_probability,
    fair_probability: opportunity.fair_probability + Math.cos(index / 3) * 0.006,
    gross_edge: opportunity.fair_probability - snapshot.midpoint_probability,
    net_edge: opportunity.fair_probability - snapshot.midpoint_probability - 0.012,
    observed_at: snapshot.observed_at
  }));
  return {
    market,
    latest_fair_value: fairValue,
    prediction_snapshots,
    fair_value_history,
    sportsbook_odds: [
      {
        id: "dk",
        bookmaker: "draftkings",
        market_type: "moneyline",
        selection: market.selection,
        american_odds: -118,
        decimal_odds: 1.85,
        implied_probability: 0.541,
        observed_at: now
      },
      {
        id: "fd",
        bookmaker: "fanduel",
        market_type: "moneyline",
        selection: market.selection,
        american_odds: -122,
        decimal_odds: 1.82,
        implied_probability: 0.55,
        observed_at: now
      },
      {
        id: "pin",
        bookmaker: "pinnacle",
        market_type: "moneyline",
        selection: market.selection,
        american_odds: -115,
        decimal_odds: 1.87,
        implied_probability: 0.535,
        observed_at: now
      }
    ]
  };
}

export function sampleOpportunityHistory(id: string): OpportunityHistoryRow[] {
  const opportunity = sampleOpportunities.find((item) => item.market_id === id) ?? sampleOpportunities[0];
  const baseTime = Date.parse("2026-04-26T14:00:00Z");
  return Array.from({ length: 18 }, (_, index) => {
    const marketProbability = opportunity.market_probability + Math.sin(index / 2) * 0.01 - 0.012 + index * 0.001;
    const fairProbability = opportunity.fair_probability + Math.cos(index / 3) * 0.006;
    const grossEdge = fairProbability - marketProbability;
    const spreadPenalty = opportunity.spread ? opportunity.spread * 0.5 : 0;
    return {
      timestamp: new Date(baseTime + index * 20 * 60 * 1000).toISOString(),
      market_probability: marketProbability,
      fair_probability: fairProbability,
      gross_edge: grossEdge,
      net_edge: grossEdge - spreadPenalty,
      confidence_score: opportunity.confidence_score
    };
  });
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
