"use client";

import type { FormEvent } from "react";
import { useMemo, useState } from "react";
import { Save } from "lucide-react";
import { clientApiUrl } from "@/lib/api";
import type { UserModel } from "@/types/api";

type FormState = {
  name: string;
  min_edge: number;
  max_spread: number;
  min_liquidity: number;
  spread_penalty_multiplier: number;
  bookmaker_weights: string;
  excluded_bookmakers: string;
};

const initialForm: FormState = {
  name: "Research Model",
  min_edge: 0.03,
  max_spread: 0.06,
  min_liquidity: 500,
  spread_penalty_multiplier: 0.5,
  bookmaker_weights: JSON.stringify({ draftkings: 1, fanduel: 1, pinnacle: 1.2 }, null, 2),
  excluded_bookmakers: ""
};

export function UserModelEditor({ models }: { models: UserModel[] }) {
  const [items, setItems] = useState(models);
  const [form, setForm] = useState(initialForm);
  const [status, setStatus] = useState<string | null>(null);

  const parsedWeights = useMemo(() => {
    try {
      return JSON.parse(form.bookmaker_weights) as Record<string, number>;
    } catch {
      return null;
    }
  }, [form.bookmaker_weights]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!parsedWeights) {
      setStatus("Bookmaker weights must be valid JSON.");
      return;
    }
    const payload = {
      name: form.name,
      config: {
        min_edge: form.min_edge,
        max_spread: form.max_spread,
        min_liquidity: form.min_liquidity,
        spread_penalty_multiplier: form.spread_penalty_multiplier,
        bookmaker_weights: parsedWeights,
        excluded_bookmakers: form.excluded_bookmakers
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean)
      }
    };
    try {
      const response = await fetch(`${clientApiUrl}/user-models`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        throw new Error("Unable to save model");
      }
      const created = (await response.json()) as UserModel;
      setItems([created, ...items]);
      setStatus("Model saved.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to save model.");
    }
  }

  return (
    <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
      <form onSubmit={submit} className="border border-line bg-ink/70 p-4">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-steel">Create Model</h2>
          <button
            type="submit"
            className="inline-flex items-center gap-2 border border-mint/50 bg-mint/10 px-3 py-2 text-sm text-mint transition hover:bg-mint/20"
          >
            <Save className="h-4 w-4" />
            Save
          </button>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField label="Name" value={form.name} onChange={(name) => setForm({ ...form, name })} />
          <NumberField label="Min edge" value={form.min_edge} step={0.005} onChange={(min_edge) => setForm({ ...form, min_edge })} />
          <NumberField label="Max spread" value={form.max_spread} step={0.005} onChange={(max_spread) => setForm({ ...form, max_spread })} />
          <NumberField label="Min liquidity" value={form.min_liquidity} step={100} onChange={(min_liquidity) => setForm({ ...form, min_liquidity })} />
          <NumberField
            label="Spread penalty multiplier"
            value={form.spread_penalty_multiplier}
            step={0.05}
            onChange={(spread_penalty_multiplier) => setForm({ ...form, spread_penalty_multiplier })}
          />
          <TextField
            label="Excluded bookmakers"
            value={form.excluded_bookmakers}
            onChange={(excluded_bookmakers) => setForm({ ...form, excluded_bookmakers })}
          />
        </div>
        <label className="mt-3 block text-xs text-steel">
          <span>Bookmaker weights JSON</span>
          <textarea
            value={form.bookmaker_weights}
            onChange={(event) => setForm({ ...form, bookmaker_weights: event.target.value })}
            rows={7}
            className="mt-1 w-full resize-y border border-line bg-panel px-3 py-2 font-mono text-sm text-white outline-none focus:border-mint"
          />
        </label>
        {status && <div className="mt-3 border border-line bg-panel/60 px-3 py-2 text-sm text-steel">{status}</div>}
      </form>

      <div className="border border-line bg-ink/70 p-4">
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-[0.16em] text-steel">Saved Models</h2>
        <div className="space-y-3">
          {items.map((model) => (
            <article key={model.id} className="border border-line bg-panel/50 p-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="font-medium text-white">{model.name}</h3>
                <span className="font-mono text-xs text-steel">{new Date(model.updated_at).toLocaleDateString()}</span>
              </div>
              <pre className="mt-3 max-h-56 overflow-auto bg-ink p-3 text-xs leading-5 text-steel">
                {JSON.stringify(model.config, null, 2)}
              </pre>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block text-xs text-steel">
      <span>{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full border border-line bg-panel px-3 py-2 text-sm text-white outline-none focus:border-mint"
      />
    </label>
  );
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
