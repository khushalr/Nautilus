"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowLeft, RefreshCw } from "lucide-react";
import { AssumptionsPanel } from "@/components/AssumptionsPanel";
import { ExplanationPanel } from "@/components/ExplanationPanel";
import { MarketCharts } from "@/components/MarketCharts";
import { apiUrl, sampleMarketDetail } from "@/lib/api";
import { formatDateTime, formatPercent, formatSignedPercent, sourceLabel } from "@/lib/format";
import type { MarketDetail } from "@/types/api";

export function MarketDetailDashboard({ marketId }: { marketId: string }) {
  const [detail, setDetail] = useState<MarketDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usingSample, setUsingSample] = useState(false);

  async function loadMarket({ sample = false }: { sample?: boolean } = {}) {
    if (sample) {
      setDetail(sampleMarketDetail(marketId));
      setUsingSample(true);
      setError(null);
      setLoading(false);
      setRefreshing(false);
      return;
    }

    setError(null);
    setRefreshing(true);
    try {
      const response = await fetch(apiUrl(`/markets/${marketId}`), { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }
      setDetail((await response.json()) as MarketDetail);
      setUsingSample(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load market.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void loadMarket();
  }, [marketId]);

  if (loading) {
    return <MarketDetailSkeleton />;
  }

  if (!detail) {
    return (
      <div className="space-y-4">
        <BackLink />
        <ErrorPanel message={error ?? "Market not loaded."} onRetry={() => void loadMarket()} onUseSample={() => void loadMarket({ sample: true })} />
      </div>
    );
  }

  const latest = detail.latest_fair_value;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <BackLink />
        <button
          type="button"
          onClick={() => void loadMarket()}
          className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm text-steel transition hover:border-mint hover:text-mint"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {error && <ErrorPanel message={error} onRetry={() => void loadMarket()} onUseSample={() => void loadMarket({ sample: true })} />}
      {usingSample && (
        <div className="border border-amber/40 bg-amber/10 px-4 py-3 text-sm text-amber">
          Showing bundled sample data because no live market response is currently loaded.
        </div>
      )}

      <section className="border border-line bg-ink/70 p-5">
        <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-start">
          <div className="max-w-3xl">
            <div className="text-xs uppercase tracking-[0.18em] text-steel">
              {sourceLabel(detail.market.source)} | {detail.market.league ?? "Unknown league"} | {detail.market.market_type}
            </div>
            <h1 className="mt-2 text-2xl font-semibold text-white">{detail.market.event_name}</h1>
            <p className="mt-2 text-sm text-steel">
              Selection: <span className="text-white">{detail.market.selection}</span> | Start:{" "}
              {formatDateTime(detail.market.start_time)}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:min-w-[520px]">
            <Metric label="Market" value={formatPercent(latest?.market_probability)} />
            <Metric label="Fair" value={formatPercent(latest?.fair_probability)} />
            <Metric label="Net edge" value={formatSignedPercent(latest?.net_edge)} tone="mint" />
            <Metric label="Confidence" value={formatPercent(latest?.confidence_score)} />
          </div>
        </div>
      </section>

      <ExplanationPanel fairValue={latest} market={detail.market} />

      <MarketCharts predictionSnapshots={detail.prediction_snapshots} fairValueHistory={detail.fair_value_history} />

      <section className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <SportsbookOddsTable detail={detail} />
        <AssumptionsPanel fairValue={latest} marketName={detail.market.event_name} />
      </section>

    </div>
  );
}

function SportsbookOddsTable({ detail }: { detail: MarketDetail }) {
  return (
    <div className="border border-line bg-ink/70 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-steel">Sportsbook Odds</h2>
      <div className="overflow-x-auto">
        <table className="min-w-[760px] w-full text-sm">
          <thead className="border-b border-line text-xs uppercase tracking-[0.14em] text-steel">
            <tr>
              <th className="px-3 py-3 text-left font-medium">Bookmaker</th>
              <th className="px-3 py-3 text-left font-medium">Selection</th>
              <th className="px-3 py-3 text-right font-medium">American</th>
              <th className="px-3 py-3 text-right font-medium">Decimal</th>
              <th className="px-3 py-3 text-right font-medium">Implied</th>
              <th className="px-3 py-3 text-right font-medium">Observed</th>
            </tr>
          </thead>
          <tbody>
            {detail.sportsbook_odds.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-steel">
                  No sportsbook odds snapshots are linked to this market yet.
                </td>
              </tr>
            ) : (
              detail.sportsbook_odds.map((line) => (
                <tr key={line.id} className="border-b border-line/70">
                  <td className="px-3 py-3 text-white">{line.bookmaker}</td>
                  <td className="px-3 py-3 text-steel">{line.selection}</td>
                  <td className="px-3 py-3 text-right font-mono">{formatAmerican(line.american_odds)}</td>
                  <td className="px-3 py-3 text-right font-mono">{line.decimal_odds?.toFixed(2) ?? "n/a"}</td>
                  <td className="px-3 py-3 text-right font-mono">{formatPercent(line.implied_probability)}</td>
                  <td className="px-3 py-3 text-right text-steel">{formatDateTime(line.observed_at)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/" className="inline-flex items-center gap-2 text-sm text-steel transition hover:text-mint">
      <ArrowLeft className="h-4 w-4" />
      Scanner
    </Link>
  );
}

function ErrorPanel({ message, onRetry, onUseSample }: { message: string; onRetry: () => void; onUseSample: () => void }) {
  return (
    <div className="flex flex-col justify-between gap-3 border border-red-400/40 bg-red-950/30 p-4 text-sm text-red-100 md:flex-row md:items-center">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <div className="font-medium text-white">Unable to load market</div>
          <div className="mt-1 text-red-100/80">{message}</div>
        </div>
      </div>
      <div className="flex gap-2">
        <button type="button" onClick={onRetry} className="border border-red-300/50 px-3 py-2 text-white transition hover:bg-red-300/10">
          Retry
        </button>
        <button type="button" onClick={onUseSample} className="border border-line px-3 py-2 text-steel transition hover:text-white">
          Sample data
        </button>
      </div>
    </div>
  );
}

function MarketDetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="h-5 w-28 animate-pulse bg-line" />
      <div className="border border-line bg-ink/70 p-5">
        <div className="h-7 w-2/3 animate-pulse bg-panel" />
        <div className="mt-4 grid gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-16 animate-pulse bg-panel" />
          ))}
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className="h-72 animate-pulse border border-line bg-ink/70" />
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value, tone = "white" }: { label: string; value: string; tone?: "white" | "mint" }) {
  return (
    <div className="border border-line bg-panel/50 p-3">
      <div className="text-xs uppercase tracking-[0.14em] text-steel">{label}</div>
      <div className={`mt-1 font-mono text-xl ${tone === "mint" ? "text-mint" : "text-white"}`}>{value}</div>
    </div>
  );
}

function formatAmerican(value: number | null): string {
  if (value == null) {
    return "n/a";
  }
  return value > 0 ? `+${value}` : String(value);
}
