export type Market = {
  id: string;
  source: string;
  external_id: string;
  event_name: string;
  league: string | null;
  market_type: string;
  selection: string;
  normalized_event_key: string;
  start_time: string | null;
  status: string;
  market_url: string | null;
  extra: Record<string, unknown>;
};

export type PredictionMarketSnapshot = {
  id: string;
  market_id: string;
  source: string;
  bid_probability: number | null;
  ask_probability: number | null;
  last_price: number | null;
  midpoint_probability: number;
  spread: number | null;
  liquidity: number | null;
  volume: number | null;
  observed_at: string;
};

export type FairValueSnapshot = {
  id: string;
  market_id: string;
  fair_probability: number;
  market_probability: number;
  gross_edge: number;
  net_edge: number;
  spread: number | null;
  liquidity: number | null;
  confidence_score: number;
  sportsbook_consensus: Record<string, unknown>;
  assumptions: Record<string, unknown>;
  explanation_json: Record<string, unknown>;
  explanation: string;
  observed_at: string;
};

export type SportsbookOddsSnapshot = {
  id: string;
  bookmaker: string;
  market_type: string;
  selection: string;
  american_odds: number | null;
  decimal_odds: number | null;
  implied_probability: number;
  observed_at: string;
};

export type Opportunity = {
  market: Market;
  fair_value: FairValueSnapshot;
};

export type MarketDetail = {
  market: Market;
  latest_fair_value: FairValueSnapshot | null;
  prediction_snapshots: PredictionMarketSnapshot[];
  fair_value_history: FairValueSnapshot[];
  sportsbook_odds: SportsbookOddsSnapshot[];
};

export type UserModel = {
  id: string;
  name: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AlertRule = {
  id: string;
  user_id: string;
  name: string;
  min_net_edge: number;
  max_spread: number | null;
  min_liquidity: number | null;
  league: string | null;
  source: string | null;
  delivery_channel: string;
  delivery_target: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};
