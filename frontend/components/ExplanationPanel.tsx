import { formatPercent, formatSignedPercent } from "@/lib/format";
import type { FairValueSnapshot } from "@/types/api";

type BookmakerExplanation = {
  bookmaker?: string;
  selection?: string;
  original_odds?: {
    american?: number | null;
    decimal?: number | null;
  };
  implied_probability?: number;
  no_vig_probability?: number;
  weight?: number;
};

export function ExplanationPanel({ fairValue }: { fairValue: FairValueSnapshot | null }) {
  const explanation = fairValue?.explanation_json ?? {};
  const bookmakers = Array.isArray(explanation.bookmakers) ? (explanation.bookmakers as BookmakerExplanation[]) : [];
  const penalties = isRecord(explanation.penalties) ? explanation.penalties : {};
  const marketProbability = isRecord(explanation.market_probability) ? explanation.market_probability : {};
  const matchedEvent = isRecord(explanation.matched_event) ? explanation.matched_event : {};

  return (
    <section className="border border-line bg-ink/70 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-steel">Fair-Value Explanation</h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Fact label="Consensus fair" value={formatPercent(numberFrom(explanation.consensus_fair_probability ?? fairValue?.fair_probability))} />
        <Fact label="Market source" value={String(marketProbability.source ?? "n/a")} />
        <Fact label="Gross edge" value={formatSignedPercent(numberFrom(explanation.gross_edge ?? fairValue?.gross_edge))} />
        <Fact label="Net edge" value={formatSignedPercent(numberFrom(explanation.net_edge ?? fairValue?.net_edge))} />
        <Fact label="Spread penalty" value={formatPercent(numberFrom(penalties.spread_penalty))} />
        <Fact label="Liquidity penalty" value={formatPercent(numberFrom(penalties.liquidity_penalty))} />
        <Fact label="Match confidence" value={formatPercent(numberFrom(matchedEvent.confidence_score))} />
        <Fact label="Final confidence" value={formatPercent(numberFrom(explanation.confidence_score ?? fairValue?.confidence_score))} />
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="min-w-[680px] w-full text-sm">
          <thead className="border-b border-line text-xs uppercase tracking-[0.14em] text-steel">
            <tr>
              <th className="px-3 py-3 text-left font-medium">Bookmaker</th>
              <th className="px-3 py-3 text-left font-medium">Selection</th>
              <th className="px-3 py-3 text-right font-medium">Odds</th>
              <th className="px-3 py-3 text-right font-medium">Implied</th>
              <th className="px-3 py-3 text-right font-medium">No-vig</th>
              <th className="px-3 py-3 text-right font-medium">Weight</th>
            </tr>
          </thead>
          <tbody>
            {bookmakers.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-steel">
                  No explanation JSON has been written for this market yet.
                </td>
              </tr>
            ) : (
              bookmakers.map((book, index) => (
                <tr key={`${book.bookmaker ?? "book"}-${index}`} className="border-b border-line/70">
                  <td className="px-3 py-3 text-white">{book.bookmaker ?? "n/a"}</td>
                  <td className="px-3 py-3 text-steel">{book.selection ?? "n/a"}</td>
                  <td className="px-3 py-3 text-right font-mono">{formatOdds(book.original_odds)}</td>
                  <td className="px-3 py-3 text-right font-mono">{formatPercent(book.implied_probability)}</td>
                  <td className="px-3 py-3 text-right font-mono text-white">{formatPercent(book.no_vig_probability)}</td>
                  <td className="px-3 py-3 text-right font-mono">{book.weight ?? 1}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {fairValue?.explanation && <p className="mt-4 text-sm leading-6 text-steel">{fairValue.explanation}</p>}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-line bg-panel/50 p-3">
      <div className="text-xs uppercase tracking-[0.14em] text-steel">{label}</div>
      <div className="mt-1 font-mono text-sm text-white">{value}</div>
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function numberFrom(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatOdds(odds: BookmakerExplanation["original_odds"]): string {
  if (!odds) {
    return "n/a";
  }
  if (typeof odds.american === "number") {
    return odds.american > 0 ? `+${odds.american}` : String(odds.american);
  }
  if (typeof odds.decimal === "number") {
    return odds.decimal.toFixed(2);
  }
  return "n/a";
}
