"use client";

import type { FormEvent } from "react";
import { useState } from "react";
import { BellOff, BellPlus, Trash2 } from "lucide-react";
import { clientApiUrl } from "@/lib/api";
import { formatPercent } from "@/lib/format";
import type { AlertRule } from "@/types/api";

type AlertForm = {
  user_id: string;
  name: string;
  min_net_edge: number;
  max_spread: string;
  min_liquidity: string;
  league: string;
  source: string;
  delivery_channel: string;
  delivery_target: string;
  is_active: boolean;
};

const initialForm: AlertForm = {
  user_id: "default",
  name: "Net edge watch",
  min_net_edge: 0.03,
  max_spread: "0.05",
  min_liquidity: "500",
  league: "",
  source: "",
  delivery_channel: "discord",
  delivery_target: "",
  is_active: true
};

export function AlertsManager({ alerts }: { alerts: AlertRule[] }) {
  const [items, setItems] = useState(alerts);
  const [form, setForm] = useState(initialForm);
  const [status, setStatus] = useState<string | null>(null);
  const activeItems = items.filter((item) => item.is_active);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus(null);
    const payload = {
      user_id: form.user_id,
      name: form.name,
      min_net_edge: form.min_net_edge,
      max_spread: optionalNumber(form.max_spread),
      min_liquidity: optionalNumber(form.min_liquidity),
      league: form.league || null,
      source: form.source || null,
      delivery_channel: form.delivery_channel,
      delivery_target: form.delivery_target,
      is_active: form.is_active
    };
    try {
      const response = await fetch(`${clientApiUrl}/alerts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) {
        throw new Error("Unable to create alert");
      }
      const created = (await response.json()) as AlertRule;
      setItems([created, ...items]);
      setStatus("Alert created.");
      setForm({ ...initialForm, delivery_target: form.delivery_target });
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to create alert.");
    }
  }

  async function disableAlert(alert: AlertRule) {
    try {
      const response = await fetch(`${clientApiUrl}/alerts/${alert.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: false })
      });
      if (!response.ok) {
        throw new Error("Unable to disable alert");
      }
      const updated = (await response.json()) as AlertRule;
      setItems(items.map((item) => (item.id === updated.id ? updated : item)));
      setStatus("Alert disabled.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to disable alert.");
    }
  }

  async function deleteAlert(alert: AlertRule) {
    try {
      const response = await fetch(`${clientApiUrl}/alerts/${alert.id}`, { method: "DELETE" });
      if (!response.ok) {
        throw new Error("Unable to delete alert");
      }
      setItems(items.filter((item) => item.id !== alert.id));
      setStatus("Alert deleted.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to delete alert.");
    }
  }

  return (
    <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
      <form onSubmit={submit} className="border border-line bg-ink/70 p-4">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-steel">Create Alert Rule</h2>
          <button
            type="submit"
            className="inline-flex items-center gap-2 border border-mint/50 bg-mint/10 px-3 py-2 text-sm text-mint transition hover:bg-mint/20"
          >
            <BellPlus className="h-4 w-4" />
            Create
          </button>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField label="User ID" value={form.user_id} onChange={(user_id) => setForm({ ...form, user_id })} />
          <TextField label="Name" value={form.name} onChange={(name) => setForm({ ...form, name })} />
          <NumberField label="Min net edge" value={form.min_net_edge} step={0.005} onChange={(min_net_edge) => setForm({ ...form, min_net_edge })} />
          <TextField label="Max spread" value={form.max_spread} onChange={(max_spread) => setForm({ ...form, max_spread })} />
          <TextField label="Min liquidity" value={form.min_liquidity} onChange={(min_liquidity) => setForm({ ...form, min_liquidity })} />
          <TextField label="League" value={form.league} onChange={(league) => setForm({ ...form, league })} />
          <TextField label="Source" value={form.source} onChange={(source) => setForm({ ...form, source })} />
          <label className="block text-xs text-steel">
            <span>Delivery channel</span>
            <select
              value={form.delivery_channel}
              onChange={(event) => setForm({ ...form, delivery_channel: event.target.value })}
              className="mt-1 w-full border border-line bg-panel px-3 py-2 text-sm text-white outline-none focus:border-mint"
            >
              <option value="discord">Discord webhook</option>
              <option value="email">Email placeholder</option>
            </select>
          </label>
        </div>
        <TextField
          label="Delivery target"
          value={form.delivery_target}
          onChange={(delivery_target) => setForm({ ...form, delivery_target })}
          placeholder="Discord webhook URL or email address"
        />
        <label className="mt-3 flex items-center gap-2 text-sm text-steel">
          <input
            type="checkbox"
            checked={form.is_active}
            onChange={(event) => setForm({ ...form, is_active: event.target.checked })}
            className="h-4 w-4 accent-[#36d399]"
          />
          Active
        </label>
        {status && <div className="mt-3 border border-line bg-panel/60 px-3 py-2 text-sm text-steel">{status}</div>}
      </form>

      <div className="border border-line bg-ink/70 p-4">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-steel">Active Alerts</h2>
          <span className="font-mono text-sm text-mint">{activeItems.length}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-[980px] w-full text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-[0.14em] text-steel">
              <tr>
                <th className="px-3 py-3 text-left font-medium">Name</th>
                <th className="px-3 py-3 text-right font-medium">Min edge</th>
                <th className="px-3 py-3 text-right font-medium">Max spread</th>
                <th className="px-3 py-3 text-right font-medium">Min liquidity</th>
                <th className="px-3 py-3 text-left font-medium">League</th>
                <th className="px-3 py-3 text-left font-medium">Source</th>
                <th className="px-3 py-3 text-left font-medium">Delivery</th>
                <th className="px-3 py-3 text-right font-medium">Status</th>
                <th className="px-3 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-steel">
                    No alert rules yet.
                  </td>
                </tr>
              ) : (
                items.map((alert) => (
                  <tr key={alert.id} className="border-b border-line/70">
                    <td className="px-3 py-3 text-white">{alert.name}</td>
                    <td className="px-3 py-3 text-right font-mono">{formatPercent(alert.min_net_edge)}</td>
                    <td className="px-3 py-3 text-right font-mono">{formatPercent(alert.max_spread)}</td>
                    <td className="px-3 py-3 text-right font-mono">{formatLiquidity(alert.min_liquidity)}</td>
                    <td className="px-3 py-3 text-steel">{alert.league ?? "All"}</td>
                    <td className="px-3 py-3 text-steel">{alert.source ?? "All"}</td>
                    <td className="px-3 py-3 text-steel">{alert.delivery_channel}</td>
                    <td className="px-3 py-3 text-right">
                      <span className={alert.is_active ? "text-mint" : "text-steel"}>{alert.is_active ? "Active" : "Disabled"}</span>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => void disableAlert(alert)}
                          disabled={!alert.is_active}
                          className="grid h-8 w-8 place-items-center border border-line text-steel transition hover:border-mint hover:text-mint disabled:cursor-not-allowed disabled:opacity-40"
                          title="Disable alert"
                          aria-label="Disable alert"
                        >
                          <BellOff className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => void deleteAlert(alert)}
                          className="grid h-8 w-8 place-items-center border border-line text-steel transition hover:border-red-300 hover:text-red-200"
                          title="Delete alert"
                          aria-label="Delete alert"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function optionalNumber(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatLiquidity(value: number | null): string {
  if (value == null) {
    return "n/a";
  }
  return `$${Math.round(value).toLocaleString()}`;
}

function TextField({
  label,
  value,
  onChange,
  placeholder
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="mt-3 block text-xs text-steel first:mt-0">
      <span>{label}</span>
      <input
        value={value}
        placeholder={placeholder}
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
