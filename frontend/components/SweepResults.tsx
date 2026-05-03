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
  const [hideZeroSignals, setHideZeroSignals] = useState(true);
  const [hideNoEvaluated, setHideNoEvaluated] = useState(true);
  const [noSideOnly, setNoSideOnly] = useState(false);
  const [yesSideOnly, setYesSideOnly] = useState(false);
  const [minDirection, setMinDirection] = useState(0);
  const [minSignals, setMinSignals] = useState(0);
  const [minAveragePnl, setMinAveragePnl] = useState(0);

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

  const sortedRows = useMemo(() => sortByBalancedScore(rows), [rows]);
  const filteredRows = useMemo(
    () =>
      filterRows(sortedRows, {
        hideZeroSignals,
        hideNoEvaluated,
        noSideOnly,
        yesSideOnly,
        minDirection,
        minSignals,
        minAveragePnl
      }),
    [sortedRows, hideZeroSignals, hideNoEvaluated, noSideOnly, yesSideOnly, minDirection, minSignals, minAveragePnl]
  );
  const recommended = filteredRows[0] ?? sortedRows[0] ?? null;

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
            <p className="mt-2 max-w-4xl text-sm leading-6 text-steel">
              Average return can be misleading for tiny contracts. Nautilus ranks rows with a balanced score that favors
              evaluated simulations, positive average P&L per $1 payout contract, directional accuracy above 50%, signal
              count, and moderate edge thresholds.
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
        <Metric label="Visible combinations" value={`${filteredRows.length}/${rows.length}`} />
        <Metric label="Recommended score" value={recommended ? balancedScore(recommended).toFixed(2) : "n/a"} />
      </section>

      <RecommendedSetting row={recommended} />

      <SweepFilters
        hideZeroSignals={hideZeroSignals}
        setHideZeroSignals={setHideZeroSignals}
        hideNoEvaluated={hideNoEvaluated}
        setHideNoEvaluated={setHideNoEvaluated}
        noSideOnly={noSideOnly}
        setNoSideOnly={setNoSideOnly}
        yesSideOnly={yesSideOnly}
        setYesSideOnly={setYesSideOnly}
        minDirection={minDirection}
        setMinDirection={setMinDirection}
        minSignals={minSignals}
        setMinSignals={setMinSignals}
        minAveragePnl={minAveragePnl}
        setMinAveragePnl={setMinAveragePnl}
      />

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
              {filteredRows.length === 0 ? (
                <tr>
                  <td colSpan={14} className="px-4 py-8 text-center text-steel">
                    {loading ? "Loading threshold sweep results..." : "No sweep rows match the current filters."}
                  </td>
                </tr>
              ) : (
                filteredRows.map((row) => (
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

function RecommendedSetting({ row }: { row: BacktestSweepResult | null }) {
  return (
    <section className="border border-mint/40 bg-mint/5 p-5">
      <div className="text-xs uppercase tracking-[0.18em] text-mint">Recommended Research Setting</div>
      {row ? (
        <div className="mt-4 grid gap-3 md:grid-cols-4 xl:grid-cols-8">
          <Metric label="Min edge" value={formatPercent(row.min_abs_edge)} />
          <Metric label="Confidence" value={formatPercent(row.min_confidence_score)} />
          <Metric label="Match" value={formatPercent(row.min_match_confidence)} />
          <Metric label="NO-side enabled" value={row.simulate_negative_edge ? "Yes" : "No"} />
          <Metric label="Signals" value={String(row.signals_created)} />
          <Metric label="Direction" value={formatPercent(row.directional_accuracy)} />
          <Metric label="Avg P&L" value={formatSignedCurrency(row.average_paper_pnl_per_contract)} />
          <Metric label="Avg return" value={formatSignedPercent(row.average_return_on_stake)} />
        </div>
      ) : (
        <p className="mt-3 text-sm text-steel">Run a threshold sweep to populate research settings.</p>
      )}
    </section>
  );
}

function SweepFilters({
  hideZeroSignals,
  setHideZeroSignals,
  hideNoEvaluated,
  setHideNoEvaluated,
  noSideOnly,
  setNoSideOnly,
  yesSideOnly,
  setYesSideOnly,
  minDirection,
  setMinDirection,
  minSignals,
  setMinSignals,
  minAveragePnl,
  setMinAveragePnl
}: {
  hideZeroSignals: boolean;
  setHideZeroSignals: (value: boolean) => void;
  hideNoEvaluated: boolean;
  setHideNoEvaluated: (value: boolean) => void;
  noSideOnly: boolean;
  setNoSideOnly: (value: boolean) => void;
  yesSideOnly: boolean;
  setYesSideOnly: (value: boolean) => void;
  minDirection: number;
  setMinDirection: (value: number) => void;
  minSignals: number;
  setMinSignals: (value: number) => void;
  minAveragePnl: number;
  setMinAveragePnl: (value: number) => void;
}) {
  return (
    <section className="grid gap-3 border border-line bg-ink/70 p-4 md:grid-cols-3 xl:grid-cols-7">
      <Checkbox label="Hide zero-signal rows" checked={hideZeroSignals} onChange={setHideZeroSignals} />
      <Checkbox label="Hide no evaluated" checked={hideNoEvaluated} onChange={setHideNoEvaluated} />
      <Checkbox label="NO-side enabled only" checked={noSideOnly} onChange={(value) => {
        setNoSideOnly(value);
        if (value) setYesSideOnly(false);
      }} />
      <Checkbox label="YES-side only" checked={yesSideOnly} onChange={(value) => {
        setYesSideOnly(value);
        if (value) setNoSideOnly(false);
      }} />
      <NumberFilter label="Min direction" value={minDirection} step={0.05} onChange={setMinDirection} />
      <NumberFilter label="Min signals" value={minSignals} step={1} onChange={setMinSignals} />
      <NumberFilter label="Min avg P&L" value={minAveragePnl} step={0.001} onChange={setMinAveragePnl} />
    </section>
  );
}

function Checkbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm text-steel">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  );
}

function NumberFilter({ label, value, step, onChange }: { label: string; value: number; step: number; onChange: (value: number) => void }) {
  return (
    <label className="space-y-1 text-xs uppercase tracking-[0.12em] text-steel">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full border border-line bg-panel px-2 py-2 font-mono text-sm text-white outline-none"
      />
    </label>
  );
}

function sortByBalancedScore(rows: BacktestSweepResult[]): BacktestSweepResult[] {
  return [...rows].sort((a, b) => balancedScore(b) - balancedScore(a));
}

function filterRows(
  rows: BacktestSweepResult[],
  filters: {
    hideZeroSignals: boolean;
    hideNoEvaluated: boolean;
    noSideOnly: boolean;
    yesSideOnly: boolean;
    minDirection: number;
    minSignals: number;
    minAveragePnl: number;
  }
): BacktestSweepResult[] {
  return rows.filter((row) => {
    const evaluated = evaluatedCount(row);
    if (filters.hideZeroSignals && row.signals_created === 0) return false;
    if (filters.hideNoEvaluated && evaluated === 0) return false;
    if (filters.noSideOnly && !row.simulate_negative_edge) return false;
    if (filters.yesSideOnly && row.evaluated_yes_side === 0) return false;
    if ((row.directional_accuracy ?? 0) < filters.minDirection) return false;
    if (row.signals_created < filters.minSignals) return false;
    if ((row.average_paper_pnl_per_contract ?? -Infinity) < filters.minAveragePnl) return false;
    return true;
  });
}

function balancedScore(row: BacktestSweepResult): number {
  const evaluated = evaluatedCount(row);
  const avgPnl = row.average_paper_pnl_per_contract ?? 0;
  const direction = row.directional_accuracy ?? 0;
  const signalCount = row.signals_created;
  const edge = row.min_abs_edge;
  const reasonableEdgeBonus = edge >= 0.005 && edge <= 0.01 ? 1.5 : edge < 0.005 ? 0.5 : 0;
  const positivePnlBonus = avgPnl > 0 ? 3 : 0;
  const directionBonus = direction > 0.5 ? (direction - 0.5) * 8 : -2;
  return evaluated * 2 + positivePnlBonus + directionBonus + Math.log10(signalCount + 1) * 2 + reasonableEdgeBonus + avgPnl * 40;
}

function evaluatedCount(row: BacktestSweepResult): number {
  return row.evaluated_yes_side + row.evaluated_no_side;
}

function formatSignedCurrency(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "n/a";
  }
  const sign = value >= 0 ? "+" : "";
  return `${sign}$${value.toFixed(4)}`;
}
