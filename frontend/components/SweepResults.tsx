"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { formatPercent, formatSignedPercent } from "@/lib/format";
import type { BacktestSweepResult } from "@/types/api";

export function SweepResults() {
  const [rows, setRows] = useState<BacktestSweepResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(apiUrl("/signals/performance/sweeps"), { cache: "no-store" });
      if (!response.ok) {
        throw new Error("Sweep results API unavailable.");
      }
      setRows((await response.json()) as BacktestSweepResult[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load sweep results.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const best = useMemo(() => bestBalance(rows), [rows]);

  return (
    <div className="space-y-6">
      <section className="border border-line bg-ink/70 p-5">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-steel">Research Sweeps</div>
            <h1 className="mt-2 text-2xl font-semibold text-white">Threshold Comparison</h1>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-steel">
              Compare historical paper-simulation results across edge, confidence, match confidence, and optional
              NO-side simulation thresholds. This is research analytics, not betting advice, financial advice, or
              evidence of executable real-world returns.
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

      <section className="grid gap-3 md:grid-cols-3">
        <Metric label="Latest run" value={rows[0]?.run_id.slice(0, 8) ?? "n/a"} />
        <Metric label="Combinations" value={String(rows.length)} />
        <Metric label="Best balance" value={best ? `${formatSignedPercent(best.average_return_on_stake)} return` : "n/a"} />
      </section>

      <section className="overflow-hidden border border-line bg-ink/70">
        <div className="border-b border-line bg-panel/70 px-4 py-3 text-xs uppercase tracking-[0.16em] text-steel">
          Threshold Results
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-[1500px] w-full text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-[0.12em] text-steel">
              <tr>
                <th className="px-4 py-3 text-right font-medium">Min Edge</th>
                <th className="px-4 py-3 text-right font-medium">Confidence</th>
                <th className="px-4 py-3 text-right font-medium">Match</th>
                <th className="px-4 py-3 text-right font-medium">NO-side</th>
                <th className="px-4 py-3 text-right font-medium">Signals</th>
                <th className="px-4 py-3 text-right font-medium">YES eval</th>
                <th className="px-4 py-3 text-right font-medium">NO eval</th>
                <th className="px-4 py-3 text-right font-medium">Direction</th>
                <th className="px-4 py-3 text-right font-medium">Avg P&L</th>
                <th className="px-4 py-3 text-right font-medium">Avg return</th>
                <th className="px-4 py-3 text-right font-medium">Edge close</th>
                <th className="px-4 py-3 text-right font-medium">Market-driven</th>
                <th className="px-4 py-3 text-right font-medium">Fair-driven</th>
                <th className="px-4 py-3 text-right font-medium">Suspicious</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={14} className="px-4 py-8 text-center text-steel">
                    {loading ? "Loading threshold sweep results..." : "No sweep results yet. Run backtest_signals with --sweep-thresholds."}
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.id} className="border-b border-line/70">
                    <td className="px-4 py-3 text-right font-mono">{formatPercent(row.min_abs_edge)}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatPercent(row.min_confidence_score)}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatPercent(row.min_match_confidence)}</td>
                    <td className="px-4 py-3 text-right font-mono">{row.simulate_negative_edge ? "Yes" : "No"}</td>
                    <td className="px-4 py-3 text-right font-mono">{row.signals_created}</td>
                    <td className="px-4 py-3 text-right font-mono">{row.evaluated_yes_side}</td>
                    <td className="px-4 py-3 text-right font-mono">{row.evaluated_no_side}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatPercent(row.directional_accuracy)}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatSignedCurrency(row.average_paper_pnl_per_contract)}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatSignedPercent(row.average_return_on_stake)}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatPercent(row.edge_close_rate)}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatPercent(row.market_driven_close_rate)}</td>
                    <td className="px-4 py-3 text-right font-mono">{formatPercent(row.fair_value_driven_close_rate)}</td>
                    <td className="px-4 py-3 text-right font-mono">{row.suspicious_invalid_count}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
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

function bestBalance(rows: BacktestSweepResult[]): BacktestSweepResult | null {
  const eligible = rows.filter((row) => row.signals_created >= 3 && row.average_return_on_stake != null);
  return eligible.sort((a, b) => (b.average_return_on_stake ?? -Infinity) - (a.average_return_on_stake ?? -Infinity))[0] ?? null;
}

function formatSignedCurrency(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "n/a";
  }
  const sign = value >= 0 ? "+" : "";
  return `${sign}$${value.toFixed(4)}`;
}
