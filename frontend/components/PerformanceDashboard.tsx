"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { formatDateTime, formatPercent, formatSignedPercent } from "@/lib/format";
import type { SignalPerformanceBucket, SignalPerformanceRow, SignalPerformanceSummary } from "@/types/api";

const emptySummary: SignalPerformanceSummary = {
  total_signals: 0,
  evaluated_signals: 0,
  simulated_long_yes_signals: 0,
  evaluated_long_yes_signals: 0,
  tracked_negative_edge_signals: 0,
  unevaluated_signals: 0,
  suspicious_invalid_signals: 0,
  skipped_invalid_signals: 0,
  average_entry_edge: null,
  average_paper_pnl_per_contract: null,
  average_return_on_stake: null,
  edge_close_rate: null,
  directional_accuracy: null,
  contains_unadjusted_liquidity: false,
  by_horizon: [],
  by_confidence_bucket: [],
  by_market_type: [],
  by_league: []
};

export function PerformanceDashboard() {
  const [summary, setSummary] = useState<SignalPerformanceSummary>(emptySummary);
  const [signals, setSignals] = useState<SignalPerformanceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [directionFilter, setDirectionFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [horizonFilter, setHorizonFilter] = useState("all");
  const [marketTypeFilter, setMarketTypeFilter] = useState("all");
  const [leagueFilter, setLeagueFilter] = useState("all");
  const [minConfidence, setMinConfidence] = useState(0);
  const [hideSuspicious, setHideSuspicious] = useState(true);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [summaryResponse, signalResponse] = await Promise.all([
        fetch(apiUrl("/signals/performance"), { cache: "no-store" }),
        fetch(apiUrl("/signals/performance/signals?limit=200"), { cache: "no-store" })
      ]);
      if (!summaryResponse.ok || !signalResponse.ok) {
        throw new Error("Performance API unavailable.");
      }
      setSummary((await summaryResponse.json()) as SignalPerformanceSummary);
      setSignals((await signalResponse.json()) as SignalPerformanceRow[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load performance.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="space-y-6">
      <section className="border border-line bg-ink/70 p-5">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-steel">Historical Signal Performance</div>
            <h1 className="mt-2 text-2xl font-semibold text-white">Paper-Trade Simulation</h1>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-steel">
              This page evaluates hypothetical signals using available historical market data. It is research analytics,
              not betting advice, not financial advice, and not evidence of executable real-world returns.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm text-steel transition hover:border-mint hover:text-mint"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </section>

      {error ? (
        <div className="flex items-start gap-3 border border-red-400/40 bg-red-950/30 p-4 text-sm text-red-100">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>{error}</div>
        </div>
      ) : null}

      {summary.contains_unadjusted_liquidity ? (
        <div className="flex items-start gap-3 border border-amber-400/40 bg-amber-950/20 p-4 text-sm text-amber-100">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>Some historical signals were evaluated without historical liquidity and may not represent executable size.</div>
        </div>
      ) : null}

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <Metric label="Total signals" value={String(summary.total_signals)} />
        <Metric label="Simulated long YES" value={String(summary.simulated_long_yes_signals)} />
        <Metric label="Evaluated long YES" value={String(summary.evaluated_long_yes_signals)} />
        <Metric label="Tracked negative" value={String(summary.tracked_negative_edge_signals)} />
        <Metric label="Unevaluated" value={String(summary.unevaluated_signals)} />
        <Metric label="Suspicious/invalid" value={String(summary.suspicious_invalid_signals)} />
        <Metric label="Edge close rate" value={formatPercent(summary.edge_close_rate)} />
        <Metric label="Directional accuracy" value={formatPercent(summary.directional_accuracy)} />
        <Metric label="Avg P&L / contract" value={formatSignedCurrency(summary.average_paper_pnl_per_contract)} />
        <Metric label="Avg return" value={formatSignedPercent(summary.average_return_on_stake)} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <BucketTable title="Horizon Results" rows={summary.by_horizon} />
        <BucketTable title="Confidence Buckets" rows={summary.by_confidence_bucket} />
        <BucketTable title="By Market Type" rows={summary.by_market_type} />
        <BucketTable title="By League" rows={summary.by_league} />
      </section>

      <SignalFilters
        rows={signals}
        directionFilter={directionFilter}
        setDirectionFilter={setDirectionFilter}
        statusFilter={statusFilter}
        setStatusFilter={setStatusFilter}
        horizonFilter={horizonFilter}
        setHorizonFilter={setHorizonFilter}
        marketTypeFilter={marketTypeFilter}
        setMarketTypeFilter={setMarketTypeFilter}
        leagueFilter={leagueFilter}
        setLeagueFilter={setLeagueFilter}
        minConfidence={minConfidence}
        setMinConfidence={setMinConfidence}
        hideSuspicious={hideSuspicious}
        setHideSuspicious={setHideSuspicious}
      />

      <SignalTable rows={filterRows(signals, { directionFilter, statusFilter, horizonFilter, marketTypeFilter, leagueFilter, minConfidence, hideSuspicious })} loading={loading} />
    </div>
  );
}

function SignalFilters({
  rows,
  directionFilter,
  setDirectionFilter,
  statusFilter,
  setStatusFilter,
  horizonFilter,
  setHorizonFilter,
  marketTypeFilter,
  setMarketTypeFilter,
  leagueFilter,
  setLeagueFilter,
  minConfidence,
  setMinConfidence,
  hideSuspicious,
  setHideSuspicious
}: {
  rows: SignalPerformanceRow[];
  directionFilter: string;
  setDirectionFilter: (value: string) => void;
  statusFilter: string;
  setStatusFilter: (value: string) => void;
  horizonFilter: string;
  setHorizonFilter: (value: string) => void;
  marketTypeFilter: string;
  setMarketTypeFilter: (value: string) => void;
  leagueFilter: string;
  setLeagueFilter: (value: string) => void;
  minConfidence: number;
  setMinConfidence: (value: number) => void;
  hideSuspicious: boolean;
  setHideSuspicious: (value: boolean) => void;
}) {
  const statuses = unique(rows.map((row) => row.evaluation_status));
  const horizons = unique(rows.map((row) => row.horizon));
  const marketTypes = unique(rows.map((row) => row.market_type));
  const leagues = unique(rows.map((row) => row.league ?? "Unknown"));

  return (
    <section className="grid gap-3 border border-line bg-ink/70 p-4 md:grid-cols-3 xl:grid-cols-7">
      <Select label="Direction" value={directionFilter} onChange={setDirectionFilter} options={["all", "positive", "negative"]} />
      <Select label="Status" value={statusFilter} onChange={setStatusFilter} options={["all", ...statuses]} />
      <Select label="Horizon" value={horizonFilter} onChange={setHorizonFilter} options={["all", ...horizons]} />
      <Select label="Market type" value={marketTypeFilter} onChange={setMarketTypeFilter} options={["all", ...marketTypes]} />
      <Select label="League" value={leagueFilter} onChange={setLeagueFilter} options={["all", ...leagues]} />
      <label className="space-y-1 text-xs uppercase tracking-[0.12em] text-steel">
        <span>Min confidence</span>
        <input
          type="number"
          min="0"
          max="1"
          step="0.05"
          value={minConfidence}
          onChange={(event) => setMinConfidence(Number(event.target.value))}
          className="w-full border border-line bg-panel px-2 py-2 font-mono text-sm text-white outline-none"
        />
      </label>
      <label className="flex items-end gap-2 pb-2 text-sm text-steel">
        <input type="checkbox" checked={hideSuspicious} onChange={(event) => setHideSuspicious(event.target.checked)} />
        Hide suspicious
      </label>
    </section>
  );
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: string[] }) {
  return (
    <label className="space-y-1 text-xs uppercase tracking-[0.12em] text-steel">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="w-full border border-line bg-panel px-2 py-2 text-sm normal-case tracking-normal text-white outline-none">
        {options.map((option) => (
          <option key={option} value={option}>
            {formatStatus(option, null)}
          </option>
        ))}
      </select>
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-line bg-panel/50 p-3">
      <div className="text-xs uppercase tracking-[0.14em] text-steel">{label}</div>
      <div className="mt-1 font-mono text-xl text-white">{value}</div>
    </div>
  );
}

function BucketTable({ title, rows }: { title: string; rows: SignalPerformanceBucket[] }) {
  return (
    <div className="border border-line bg-ink/70 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-steel">{title}</h2>
      <table className="w-full text-sm">
        <thead className="border-b border-line text-xs uppercase tracking-[0.12em] text-steel">
          <tr>
            <th className="py-2 text-left font-medium">Group</th>
            <th className="py-2 text-right font-medium">Signals</th>
            <th className="py-2 text-right font-medium">Uneval.</th>
            <th className="py-2 text-right font-medium">Edge close</th>
            <th className="py-2 text-right font-medium">Direction</th>
            <th className="py-2 text-right font-medium">Avg P&L</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={6} className="py-5 text-center text-steel">
                No backtest results yet.
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={row.key} className="border-b border-line/70">
                <td className="py-2 text-white">{row.key}</td>
                <td className="py-2 text-right font-mono">{row.evaluated_signals}/{row.total_signals}</td>
                <td className="py-2 text-right font-mono">{row.unevaluated_signals}</td>
                <td className="py-2 text-right font-mono">{formatPercent(row.edge_close_rate)}</td>
                <td className="py-2 text-right font-mono">{formatPercent(row.directional_accuracy)}</td>
                <td className="py-2 text-right font-mono">{formatSignedCurrency(row.average_paper_pnl_per_contract)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function SignalTable({ rows, loading }: { rows: SignalPerformanceRow[]; loading: boolean }) {
  return (
    <section className="overflow-hidden border border-line bg-ink/70">
      <div className="border-b border-line bg-panel/70 px-4 py-3 text-xs uppercase tracking-[0.16em] text-steel">
        Signal Rows
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[1680px] w-full text-sm">
          <thead className="border-b border-line text-xs uppercase tracking-[0.12em] text-steel">
            <tr>
              <th className="px-4 py-3 text-left font-medium">Timestamp</th>
              <th className="px-4 py-3 text-left font-medium">Market</th>
              <th className="px-4 py-3 text-left font-medium">Outcome</th>
              <th className="px-4 py-3 text-right font-medium">Market YES</th>
              <th className="px-4 py-3 text-right font-medium">Sportsbook Fair</th>
              <th className="px-4 py-3 text-right font-medium">Entry edge</th>
              <th className="px-4 py-3 text-right font-medium">Raw side</th>
              <th className="px-4 py-3 text-right font-medium">Raw price</th>
              <th className="px-4 py-3 text-right font-medium">Derived YES</th>
              <th className="px-4 py-3 text-right font-medium">Horizon</th>
              <th className="px-4 py-3 text-left font-medium">Status</th>
              <th className="px-4 py-3 text-right font-medium">Paper P&L</th>
              <th className="px-4 py-3 text-right font-medium">Return</th>
              <th className="px-4 py-3 text-right font-medium">Direction</th>
              <th className="px-4 py-3 text-right font-medium">Edge closed</th>
              <th className="px-4 py-3 text-right font-medium">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={16} className="px-4 py-8 text-center text-steel">
                  {loading ? "Loading historical signal performance..." : "No historical paper-trade simulation rows yet."}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={`${row.signal_id}-${row.horizon}`} className="border-b border-line/70">
                  <td className="px-4 py-3 text-steel">{formatDateTime(row.timestamp)}</td>
                  <td className="px-4 py-3 text-white">{row.title}</td>
                  <td className="px-4 py-3 text-steel">{row.display_outcome ?? "n/a"}</td>
                  <td className="px-4 py-3 text-right font-mono">{formatPercent(row.entry_market_yes_probability)}</td>
                  <td className="px-4 py-3 text-right font-mono">{formatPercent(row.entry_sportsbook_fair_probability)}</td>
                  <td className="px-4 py-3 text-right font-mono">{formatSignedPercent(row.entry_net_edge)}</td>
                  <td className="px-4 py-3 text-right font-mono">{row.raw_outcome_side ?? "n/a"}</td>
                  <td className="px-4 py-3 text-right font-mono">{formatPercent(row.raw_historical_price)}</td>
                  <td className="px-4 py-3 text-right font-mono">{formatPercent(row.derived_market_yes_probability)}</td>
                  <td className="px-4 py-3 text-right font-mono">{row.horizon}</td>
                  <td className="px-4 py-3 text-steel" title={row.suspicion_reason ?? row.skip_reason ?? undefined}>{formatStatus(row.evaluation_status, row.skip_reason)}</td>
                  <td className="px-4 py-3 text-right font-mono">{formatSignedCurrency(row.paper_pnl_per_contract)}</td>
                  <td className="px-4 py-3 text-right font-mono">{formatSignedPercent(row.return_on_stake)}</td>
                  <td className="px-4 py-3 text-right">{formatBoolean(row.moved_expected_direction)}</td>
                  <td className="px-4 py-3 text-right">{formatBoolean(row.did_edge_close)}</td>
                  <td className="px-4 py-3 text-right font-mono">{formatPercent(row.confidence_score)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function formatSignedCurrency(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "n/a";
  }
  const sign = value >= 0 ? "+" : "";
  return `${sign}$${value.toFixed(4)}`;
}

function formatBoolean(value: boolean | null): string {
  if (value == null) {
    return "n/a";
  }
  return value ? "Yes" : "No";
}

function formatStatus(status: string, skipReason: string | null): string {
  const labels: Record<string, string> = {
    all: "All",
    positive: "Positive edge only",
    negative: "Negative edge only",
    evaluated: "Evaluated",
    missing_future_price: "Missing future price",
    missing_future_fair: "Missing future fair",
    invalid_probability: "Invalid probability",
    negative_edge_no_long_simulation: "No long-YES simulation",
    suspicious_probability_orientation: "Suspicious orientation"
  };
  return labels[status] ?? skipReason ?? status;
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values)).filter(Boolean).sort();
}

function filterRows(
  rows: SignalPerformanceRow[],
  filters: {
    directionFilter: string;
    statusFilter: string;
    horizonFilter: string;
    marketTypeFilter: string;
    leagueFilter: string;
    minConfidence: number;
    hideSuspicious: boolean;
  }
): SignalPerformanceRow[] {
  return rows.filter((row) => {
    if (filters.hideSuspicious && row.signal_category === "suspicious_or_invalid") return false;
    if (filters.directionFilter === "positive" && row.direction !== "possible_yes_underpricing") return false;
    if (filters.directionFilter === "negative" && row.direction !== "possible_yes_overpricing") return false;
    if (filters.statusFilter !== "all" && row.evaluation_status !== filters.statusFilter) return false;
    if (filters.horizonFilter !== "all" && row.horizon !== filters.horizonFilter) return false;
    if (filters.marketTypeFilter !== "all" && row.market_type !== filters.marketTypeFilter) return false;
    if (filters.leagueFilter !== "all" && (row.league ?? "Unknown") !== filters.leagueFilter) return false;
    if (row.confidence_score < filters.minConfidence) return false;
    return true;
  });
}
