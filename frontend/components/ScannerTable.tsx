import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import type { Opportunity } from "@/types/api";
import { formatDateTime, formatPercent, formatSignedPercent, sourceLabel } from "@/lib/format";

export function ScannerTable({ opportunities }: { opportunities: Opportunity[] }) {
  return (
    <div className="overflow-hidden border border-line bg-ink/70">
      <div className="grid grid-cols-2 border-b border-line bg-panel/70 px-4 py-3 text-xs uppercase tracking-[0.16em] text-steel md:grid-cols-4">
        <div>Scanner</div>
        <div className="text-right md:col-span-3">Latest fair-value opportunities</div>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-[1320px] w-full text-left text-sm">
          <thead className="border-b border-line text-xs uppercase tracking-[0.14em] text-steel">
            <tr>
              <th className="px-4 py-3 font-medium">Event title</th>
              <th className="px-4 py-3 font-medium">League</th>
              <th className="px-4 py-3 font-medium">Start time</th>
              <th className="px-4 py-3 font-medium">Source</th>
              <th className="px-4 py-3 text-right font-medium">Market probability</th>
              <th className="px-4 py-3 text-right font-medium">Fair probability</th>
              <th className="px-4 py-3 text-right font-medium">Gross edge</th>
              <th className="px-4 py-3 text-right font-medium">Net edge</th>
              <th className="px-4 py-3 text-right font-medium">Spread</th>
              <th className="px-4 py-3 text-right font-medium">Liquidity</th>
              <th className="px-4 py-3 text-right font-medium">Confidence</th>
              <th className="px-4 py-3 text-right font-medium">Last updated</th>
            </tr>
          </thead>
          <tbody>
            {opportunities.length === 0 ? (
              <tr>
                <td className="px-4 py-8 text-center text-steel" colSpan={12}>
                  No opportunities match the current filters.
                </td>
              </tr>
            ) : (
              opportunities.map(({ market, fair_value }) => (
                <tr key={`${market.id}-${fair_value.id}`} className="border-b border-line/70 transition hover:bg-panel/70">
                  <td className="px-4 py-4">
                    <Link href={`/markets/${market.id}`} className="group flex items-start justify-between gap-3">
                      <div>
                        <div className="font-medium text-white">{market.event_name}</div>
                        <div className="mt-1 text-xs text-steel">{market.selection}</div>
                      </div>
                      <ArrowUpRight className="mt-1 h-4 w-4 shrink-0 text-steel transition group-hover:text-mint" />
                    </Link>
                  </td>
                  <td className="px-4 py-4 text-steel">{market.league ?? "Unknown"}</td>
                  <td className="px-4 py-4 text-steel">{formatDateTime(market.start_time)}</td>
                  <td className="px-4 py-4 text-steel">{sourceLabel(market.source)}</td>
                  <td className="px-4 py-4 text-right font-mono">{formatPercent(fair_value.market_probability)}</td>
                  <td className="px-4 py-4 text-right font-mono text-white">{formatPercent(fair_value.fair_probability)}</td>
                  <td className="px-4 py-4 text-right font-mono">{formatSignedPercent(fair_value.gross_edge)}</td>
                  <td className="px-4 py-4 text-right font-mono text-mint">{formatSignedPercent(fair_value.net_edge)}</td>
                  <td className="px-4 py-4 text-right font-mono">{formatPercent(fair_value.spread)}</td>
                  <td className="px-4 py-4 text-right font-mono">{formatLiquidity(fair_value.liquidity)}</td>
                  <td className="px-4 py-4 text-right">
                    <span className="inline-flex min-w-16 justify-center border border-mint/40 bg-mint/10 px-2 py-1 font-mono text-mint">
                      {formatPercent(fair_value.confidence_score)}
                    </span>
                  </td>
                  <td className="px-4 py-4 text-right text-steel">{formatDateTime(fair_value.observed_at)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatLiquidity(value: number | null): string {
  if (value == null) {
    return "n/a";
  }
  return `$${Math.round(value).toLocaleString()}`;
}
