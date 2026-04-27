"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, RefreshCw, RotateCcw } from "lucide-react";
import { ScannerTable } from "@/components/ScannerTable";
import { apiUrl, sampleOpportunities } from "@/lib/api";
import { formatPercent, formatSignedPercent } from "@/lib/format";
import type { Opportunity } from "@/types/api";

type Filters = {
  minNetEdge: number;
  maxSpread: number;
  minLiquidity: number;
  league: string;
  source: string;
};

const defaultFilters: Filters = {
  minNetEdge: 0,
  maxSpread: 1,
  minLiquidity: 0,
  league: "all",
  source: "all"
};

export function ScannerDashboard() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [filters, setFilters] = useState(defaultFilters);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usingSample, setUsingSample] = useState(false);

  async function loadOpportunities({ sample = false }: { sample?: boolean } = {}) {
    if (sample) {
      setOpportunities(sampleOpportunities);
      setUsingSample(true);
      setError(null);
      setLoading(false);
      setRefreshing(false);
      return;
    }

    setError(null);
    setRefreshing(true);
    try {
      const response = await fetch(apiUrl("/opportunities?min_net_edge=-1&limit=500"), { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }
      setOpportunities((await response.json()) as Opportunity[]);
      setUsingSample(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load opportunities.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void loadOpportunities();
  }, []);

  const filterOptions = useMemo(() => {
    const leagues = Array.from(new Set(opportunities.map((item) => item.league).filter(Boolean) as string[])).sort();
    const sources = Array.from(new Set(opportunities.map((item) => item.source))).sort();
    return { leagues, sources };
  }, [opportunities]);

  const filtered = useMemo(() => {
    return opportunities
      .filter((item) => item.net_edge >= filters.minNetEdge)
      .filter((item) => item.spread == null || item.spread <= filters.maxSpread)
      .filter((item) => item.liquidity == null || item.liquidity >= filters.minLiquidity)
      .filter((item) => filters.league === "all" || item.league === filters.league)
      .filter((item) => filters.source === "all" || item.source === filters.source)
      .sort((a, b) => b.net_edge - a.net_edge);
  }, [filters, opportunities]);

  const best = filtered[0];
  const averageConfidence = filtered.reduce((total, item) => total + item.confidence_score, 0) / Math.max(filtered.length, 1);

  return (
    <div className="space-y-6">
      <section className="grid gap-4 md:grid-cols-4">
        <Metric label="Visible opportunities" value={String(filtered.length)} />
        <Metric label="Best net edge" value={formatSignedPercent(best?.net_edge)} tone="mint" />
        <Metric label="Best gross edge" value={formatSignedPercent(best?.gross_edge)} />
        <Metric label="Avg confidence" value={formatPercent(averageConfidence)} />
      </section>

      <section className="border border-line bg-ink/70 p-5">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
          <div className="max-w-4xl">
            <h1 className="text-2xl font-semibold tracking-normal text-white">Nautilus scanner</h1>
            <p className="mt-2 text-sm leading-6 text-steel">
              Nautilus ranks prediction-market opportunities by comparing market price with weighted no-vig sportsbook
              fair value, then subtracting spread and liquidity penalties.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void loadOpportunities()}
              className="inline-flex items-center gap-2 border border-line px-3 py-2 text-sm text-steel transition hover:border-mint hover:text-mint"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>
            <button
              type="button"
              onClick={() => setFilters(defaultFilters)}
              className="grid h-10 w-10 place-items-center border border-line text-steel transition hover:border-mint hover:text-mint"
              title="Reset filters"
              aria-label="Reset filters"
            >
              <RotateCcw className="h-4 w-4" />
            </button>
          </div>
        </div>
      </section>

      <FilterPanel filters={filters} setFilters={setFilters} leagues={filterOptions.leagues} sources={filterOptions.sources} />

      {error && (
        <ErrorPanel
          message={error}
          onRetry={() => void loadOpportunities()}
          onUseSample={() => void loadOpportunities({ sample: true })}
        />
      )}
      {usingSample && (
        <div className="border border-amber/40 bg-amber/10 px-4 py-3 text-sm text-amber">
          Showing bundled sample data because no live API response is currently loaded.
        </div>
      )}
      {loading ? <ScannerSkeleton /> : <ScannerTable opportunities={filtered} />}
    </div>
  );
}

function FilterPanel({
  filters,
  setFilters,
  leagues,
  sources
}: {
  filters: Filters;
  setFilters: (filters: Filters) => void;
  leagues: string[];
  sources: string[];
}) {
  return (
    <section className="border border-line bg-ink/70 p-4">
      <div className="mb-3 text-xs uppercase tracking-[0.16em] text-steel">Filters</div>
      <div className="grid gap-3 md:grid-cols-5">
        <NumberFilter label="Min net edge" value={filters.minNetEdge} step={0.005} onChange={(minNetEdge) => setFilters({ ...filters, minNetEdge })} />
        <NumberFilter label="Max spread" value={filters.maxSpread} step={0.005} onChange={(maxSpread) => setFilters({ ...filters, maxSpread })} />
        <NumberFilter label="Min liquidity" value={filters.minLiquidity} step={100} onChange={(minLiquidity) => setFilters({ ...filters, minLiquidity })} />
        <SelectFilter label="League" value={filters.league} options={leagues} onChange={(league) => setFilters({ ...filters, league })} />
        <SelectFilter label="Source" value={filters.source} options={sources} onChange={(source) => setFilters({ ...filters, source })} />
      </div>
    </section>
  );
}

function NumberFilter({ label, value, step, onChange }: { label: string; value: number; step: number; onChange: (value: number) => void }) {
  return (
    <label className="block text-xs text-steel">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-1 w-full border border-line bg-panel px-3 py-2 font-mono text-sm text-white outline-none focus:border-mint"
      />
    </label>
  );
}

function SelectFilter({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="block text-xs text-steel">
      <span>{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full border border-line bg-panel px-3 py-2 text-sm text-white outline-none focus:border-mint"
      >
        <option value="all">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function ErrorPanel({ message, onRetry, onUseSample }: { message: string; onRetry: () => void; onUseSample: () => void }) {
  return (
    <div className="flex flex-col justify-between gap-3 border border-red-400/40 bg-red-950/30 p-4 text-sm text-red-100 md:flex-row md:items-center">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <div className="font-medium text-white">Unable to load opportunities</div>
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

function ScannerSkeleton() {
  return (
    <div className="border border-line bg-ink/70 p-4">
      <div className="h-4 w-40 animate-pulse bg-line" />
      <div className="mt-4 space-y-3">
        {Array.from({ length: 8 }).map((_, index) => (
          <div key={index} className="h-10 animate-pulse bg-panel" />
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value, tone = "white" }: { label: string; value: string; tone?: "white" | "mint" }) {
  return (
    <div className="border border-line bg-ink/70 p-4">
      <div className="text-xs uppercase tracking-[0.16em] text-steel">{label}</div>
      <div className={`mt-2 font-mono text-2xl ${tone === "mint" ? "text-mint" : "text-white"}`}>{value}</div>
    </div>
  );
}
