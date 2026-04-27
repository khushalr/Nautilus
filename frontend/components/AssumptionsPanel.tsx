"use client";

import { useMemo, useState } from "react";
import { RotateCcw, Save } from "lucide-react";
import { apiUrl } from "@/lib/api";
import { formatSignedPercent } from "@/lib/format";
import type { FairValueSnapshot } from "@/types/api";

type Assumptions = {
  min_edge: number;
  max_spread: number;
  min_liquidity: number;
  spread_penalty_multiplier: number;
  liquidity_penalty_multiplier: number;
  bookmaker_weights: string;
  excluded_bookmakers: string;
};

const defaults: Assumptions = {
  min_edge: 0.03,
  max_spread: 0.06,
  min_liquidity: 500,
  spread_penalty_multiplier: 0.5,
  liquidity_penalty_multiplier: 0.02,
  bookmaker_weights: JSON.stringify({ draftkings: 1, fanduel: 1, pinnacle: 1.2 }, null, 2),
  excluded_bookmakers: ""
};

export function AssumptionsPanel({
  fairValue,
  marketName
}: {
  fairValue: FairValueSnapshot | null;
  marketName: string;
}) {
  const [assumptions, setAssumptions] = useState(() => assumptionsFromFairValue(fairValue));
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const adjustedEdge = useMemo(() => {
    const grossEdge = fairValue?.gross_edge ?? 0;
    const spreadPenalty = (fairValue?.spread ?? 0) * assumptions.spread_penalty_multiplier;
    const liquidity = fairValue?.liquidity ?? null;
    const liquidityShortfall =
      liquidity == null || liquidity >= assumptions.min_liquidity
        ? liquidity == null
          ? 1
          : 0
        : (assumptions.min_liquidity - liquidity) / assumptions.min_liquidity;
    return grossEdge - spreadPenalty - liquidityShortfall * assumptions.liquidity_penalty_multiplier;
  }, [assumptions, fairValue]);

  async function saveModel() {
    setStatus(null);
    let bookmakerWeights: Record<string, number>;
    try {
      bookmakerWeights = JSON.parse(assumptions.bookmaker_weights) as Record<string, number>;
    } catch {
      setStatus("Bookmaker weights must be valid JSON.");
      return;
    }

    setSaving(true);
    try {
      const response = await fetch(apiUrl("/user-models"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `${marketName} model`,
          config: {
            min_edge: assumptions.min_edge,
            max_spread: assumptions.max_spread,
            min_liquidity: assumptions.min_liquidity,
            spread_penalty_multiplier: assumptions.spread_penalty_multiplier,
            liquidity_penalty_multiplier: assumptions.liquidity_penalty_multiplier,
            bookmaker_weights: bookmakerWeights,
            excluded_bookmakers: assumptions.excluded_bookmakers
              .split(",")
              .map((bookmaker) => bookmaker.trim())
              .filter(Boolean)
          }
        })
      });
      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }
      setStatus("Saved as user model config JSON.");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Unable to save model.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="border border-line bg-ink/70 p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-steel">Editable Assumptions</h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setAssumptions(assumptionsFromFairValue(fairValue))}
            className="grid h-8 w-8 place-items-center border border-line text-steel transition hover:border-mint hover:text-mint"
            title="Reset assumptions"
            aria-label="Reset assumptions"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => void saveModel()}
            className="inline-flex h-8 items-center gap-2 border border-mint/50 bg-mint/10 px-3 text-sm text-mint transition hover:bg-mint/20"
          >
            <Save className="h-4 w-4" />
            {saving ? "Saving" : "Save"}
          </button>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <NumberField label="Min edge" value={assumptions.min_edge} step={0.005} onChange={(min_edge) => setAssumptions({ ...assumptions, min_edge })} />
        <NumberField label="Max spread" value={assumptions.max_spread} step={0.005} onChange={(max_spread) => setAssumptions({ ...assumptions, max_spread })} />
        <NumberField label="Min liquidity" value={assumptions.min_liquidity} step={100} onChange={(min_liquidity) => setAssumptions({ ...assumptions, min_liquidity })} />
        <NumberField
          label="Spread penalty multiplier"
          value={assumptions.spread_penalty_multiplier}
          step={0.05}
          onChange={(spread_penalty_multiplier) => setAssumptions({ ...assumptions, spread_penalty_multiplier })}
        />
      </div>
      <label className="mt-3 block text-xs text-steel">
        <span>Bookmaker weights</span>
        <textarea
          value={assumptions.bookmaker_weights}
          onChange={(event) => setAssumptions({ ...assumptions, bookmaker_weights: event.target.value })}
          rows={5}
          className="mt-1 w-full resize-y border border-line bg-panel px-3 py-2 font-mono text-sm text-white outline-none focus:border-mint"
        />
      </label>
      <label className="mt-3 block text-xs text-steel">
        <span>Excluded bookmakers</span>
        <input
          value={assumptions.excluded_bookmakers}
          onChange={(event) => setAssumptions({ ...assumptions, excluded_bookmakers: event.target.value })}
          placeholder="draftkings, fanduel"
          className="mt-1 w-full border border-line bg-panel px-3 py-2 text-sm text-white outline-none focus:border-mint"
        />
      </label>
      <div className="mt-4 border border-line bg-panel/50 p-3">
        <div className="text-xs uppercase tracking-[0.14em] text-steel">Adjusted net edge</div>
        <div className="mt-1 font-mono text-2xl text-mint">{formatSignedPercent(adjustedEdge)}</div>
      </div>
      {status && <div className="mt-3 border border-line bg-panel/60 px-3 py-2 text-sm text-steel">{status}</div>}
    </section>
  );
}

function assumptionsFromFairValue(fairValue: FairValueSnapshot | null): Assumptions {
  const config = fairValue?.assumptions ?? {};
  return {
    min_edge: numberFrom(config.min_edge, defaults.min_edge),
    max_spread: numberFrom(config.max_spread, defaults.max_spread),
    min_liquidity: numberFrom(config.min_liquidity, defaults.min_liquidity),
    spread_penalty_multiplier: numberFrom(config.spread_penalty_multiplier, defaults.spread_penalty_multiplier),
    liquidity_penalty_multiplier: numberFrom(config.liquidity_penalty_multiplier, defaults.liquidity_penalty_multiplier),
    bookmaker_weights: JSON.stringify(config.bookmaker_weights ?? JSON.parse(defaults.bookmaker_weights), null, 2),
    excluded_bookmakers: Array.isArray(config.excluded_bookmakers) ? config.excluded_bookmakers.join(", ") : ""
  };
}

function numberFrom(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function NumberField({
  label,
  value,
  step,
  onChange
}: {
  label: string;
  value: number;
  step: number;
  onChange: (value: number) => void;
}) {
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
