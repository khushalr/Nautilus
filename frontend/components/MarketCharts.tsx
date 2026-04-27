"use client";

import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import type { FairValueSnapshot, PredictionMarketSnapshot } from "@/types/api";
import { formatPercent } from "@/lib/format";

type ChartDatum = {
  time: string;
  market: number;
  fair: number;
  edge: number;
};

export function MarketCharts({
  predictionSnapshots,
  fairValueHistory
}: {
  predictionSnapshots: PredictionMarketSnapshot[];
  fairValueHistory: FairValueSnapshot[];
}) {
  const data = buildChartData(predictionSnapshots, fairValueHistory);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <ChartPanel title="Market YES vs Sportsbook Fair">
        <ChartFrame data={data}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data}>
              <CartesianGrid stroke="#233044" strokeDasharray="3 3" />
              <XAxis dataKey="time" stroke="#9fb0c3" tick={{ fontSize: 11 }} />
              <YAxis stroke="#9fb0c3" tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`} width={44} />
              <Tooltip content={<ChartTooltip />} />
              <Line type="monotone" dataKey="market" stroke="#36d399" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="fair" stroke="#f5c451" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartFrame>
      </ChartPanel>
      <ChartPanel title="Sportsbook Fair">
        <ChartFrame data={data}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data}>
              <CartesianGrid stroke="#233044" strokeDasharray="3 3" />
              <XAxis dataKey="time" stroke="#9fb0c3" tick={{ fontSize: 11 }} />
              <YAxis stroke="#9fb0c3" tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`} width={44} />
              <Tooltip content={<ChartTooltip />} />
              <Line type="monotone" dataKey="fair" stroke="#f5c451" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="market" stroke="#5d6f86" strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartFrame>
      </ChartPanel>
      <ChartPanel title="Edge Over Time">
        <ChartFrame data={data}>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={data}>
              <CartesianGrid stroke="#233044" strokeDasharray="3 3" />
              <XAxis dataKey="time" stroke="#9fb0c3" tick={{ fontSize: 11 }} />
              <YAxis stroke="#9fb0c3" tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`} width={44} />
              <Tooltip content={<ChartTooltip />} />
              <Area type="monotone" dataKey="edge" stroke="#36d399" fill="#36d39933" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartFrame>
      </ChartPanel>
    </div>
  );
}

function ChartPanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border border-line bg-ink/70 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-steel">{title}</h2>
      {children}
    </section>
  );
}

function ChartFrame({ data, children }: { data: ChartDatum[]; children: ReactNode }) {
  if (data.length === 0) {
    return <div className="grid h-[260px] place-items-center border border-line bg-panel/40 text-sm text-steel">No history yet</div>;
  }
  return <>{children}</>;
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number }>; label?: string }) {
  if (!active || !payload?.length) {
    return null;
  }
  return (
    <div className="border border-line bg-ink px-3 py-2 text-xs shadow-xl">
      <div className="mb-1 font-medium text-white">{label}</div>
      {payload.map((item) => (
        <div key={item.name} className="flex min-w-32 justify-between gap-4 text-steel">
          <span>{item.name}</span>
          <span className="font-mono text-white">{formatPercent(item.value)}</span>
        </div>
      ))}
    </div>
  );
}

function buildChartData(
  predictionSnapshots: PredictionMarketSnapshot[],
  fairValueHistory: FairValueSnapshot[]
): ChartDatum[] {
  if (fairValueHistory.length > 0) {
    return [...fairValueHistory]
      .sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at))
      .map((snapshot) => ({
        time: new Date(snapshot.observed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        market: snapshot.market_probability,
        fair: snapshot.fair_probability,
        edge: snapshot.net_edge
      }));
  }

  const fairByTime = new Map(fairValueHistory.map((item) => [item.observed_at, item]));
  return [...predictionSnapshots]
    .sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at))
    .map((snapshot) => {
      const fair = fairByTime.get(snapshot.observed_at);
      const fallbackFair = fairValueHistory[fairValueHistory.length - 1];
      const fairProbability = fair?.fair_probability ?? fallbackFair?.fair_probability ?? snapshot.midpoint_probability;
      return {
        time: new Date(snapshot.observed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        market: snapshot.midpoint_probability,
        fair: fairProbability,
        edge: fair?.net_edge ?? fairProbability - snapshot.midpoint_probability
      };
    });
}
