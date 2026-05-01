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
  market_id: string;
  title: string;
  source: string;
  external_id: string;
  league: string | null;
  market_type: string;
  outcome: string | null;
  display_outcome: string | null;
  start_time: string | null;
  status: string;
  market_url: string | null;
  market_probability: number;
  fair_probability: number;
  gross_edge: number;
  net_edge: number;
  spread: number | null;
  liquidity: number | null;
  confidence_score: number;
  matched_sportsbook_category: string | null;
  matched_selection: string | null;
  match_confidence: number | null;
  sportsbooks_used: string[];
  last_updated: string;
  assumptions?: Record<string, unknown>;
  explanation_json?: Record<string, unknown>;
  market_extra?: Record<string, unknown>;
};

export type OpportunityHistoryRow = {
  timestamp: string;
  market_probability: number;
  fair_probability: number;
  gross_edge: number;
  net_edge: number;
  confidence_score: number;
};

export type SignalPerformanceBucket = {
  key: string;
  total_signals: number;
  evaluated_signals: number;
  average_entry_edge: number | null;
  average_paper_pnl_per_contract: number | null;
  average_return_on_stake: number | null;
  edge_close_rate: number | null;
  directional_accuracy: number | null;
};

export type SignalPerformanceSummary = {
  total_signals: number;
  evaluated_signals: number;
  average_entry_edge: number | null;
  average_paper_pnl_per_contract: number | null;
  average_return_on_stake: number | null;
  edge_close_rate: number | null;
  directional_accuracy: number | null;
  by_horizon: SignalPerformanceBucket[];
  by_confidence_bucket: SignalPerformanceBucket[];
  by_market_type: SignalPerformanceBucket[];
  by_league: SignalPerformanceBucket[];
};

export type SignalPerformanceRow = {
  signal_id: string;
  market_id: string;
  timestamp: string;
  title: string;
  display_outcome: string | null;
  market_type: string;
  league: string | null;
  direction: string;
  entry_market_yes_probability: number;
  entry_sportsbook_fair_probability: number;
  entry_net_edge: number;
  horizon: string;
  exit_market_yes_probability: number | null;
  paper_pnl_per_contract: number | null;
  return_on_stake: number | null;
  did_edge_close: boolean | null;
  moved_expected_direction: boolean | null;
  confidence_score: number;
  skip_reason: string | null;
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
