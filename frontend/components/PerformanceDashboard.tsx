"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { formatDateTime, formatPercent, formatSignedPercent } from "@/lib/format";
import type { SignalPerformanceBucket, SignalPerformanceRow, SignalPerformanceSummary } from "@/types/api";

const emptySummary: SignalPerformanceSummary = {
  total_signals: 0,
  evaluated_signals: 0,
  average_entry_edge: null,
  average_paper_pnl_per_contract: null,
  average_return_on_stake: null,
  edge_close_rate: null,
  directional_accuracy: null,
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

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <Metric label="Total signals" value={String(summary.total_signals)} />
        <Metric label="Evaluated" value={String(summary.evaluated_signals)} />
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

      <SignalTable rows={signals} loading={loading} />
    </div>
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
            <th className="py-2 text-right font-medium">Edge close</th>
            <th className="py-2 text-right font-medium">Direction</th>
            <th className="py-2 text-right font-medium">Avg P&L</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={5} className="py-5 text-center text-steel">
                No backtest results yet.
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={row.key} className="border-b border-line/70">
                <td className="py-2 text-white">{row.key}</td>
                <td className="py-2 text-right font-mono">{row.evaluated_signals}/{row.total_signals}</td>
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
        <table className="min-w-[1280px] w-full text-sm">
          <thead className="border-b border-line text-xs uppercase tracking-[0.12em] text-steel">
            <tr>
              <th className="px-4 py-3 text-left font-medium">Timestamp</th>
              <th className="px-4 py-3 text-left font-medium">Market</th>
              <th className="px-4 py-3 text-left font-medium">Outcome</th>
              <th className="px-4 py-3 text-right font-medium">Entry edge</th>
              <th className="px-4 py-3 text-right font-medium">Horizon</th>
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
                <td colSpan={10} className="px-4 py-8 text-center text-steel">
                  {loading ? "Loading historical signal performance..." : "No historical paper-trade simulation rows yet."}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={`${row.signal_id}-${row.horizon}`} className="border-b border-line/70">
                  <td className="px-4 py-3 text-steel">{formatDateTime(row.timestamp)}</td>
                  <td className="px-4 py-3 text-white">{row.title}</td>
                  <td className="px-4 py-3 text-steel">{row.display_outcome ?? "n/a"}</td>
                  <td className="px-4 py-3 text-right font-mono">{formatSignedPercent(row.entry_net_edge)}</td>
                  <td className="px-4 py-3 text-right font-mono">{row.horizon}</td>
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
