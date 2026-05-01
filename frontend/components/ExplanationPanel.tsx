import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { formatPercent, formatSignedPercent } from "@/lib/format";
import type { FairValueSnapshot, Market } from "@/types/api";

type BookmakerExplanation = {
  bookmaker?: string;
  selection?: string;
  target_outcome?: string;
  original_odds?: {
    american?: number | null;
    decimal?: number | null;
  };
  implied_probability?: number;
  no_vig_probability?: number;
  outright_market_total_implied_probability?: number;
  outcome_match_score?: number;
  is_inverse_no_selection?: boolean;
  weight?: number;
};

export function ExplanationPanel({
  fairValue,
  market
}: {
  fairValue: FairValueSnapshot | null;
  market: Market;
}) {
  const explanation = fairValue?.explanation_json ?? {};
  const bookmakers = Array.isArray(explanation.bookmakers) ? (explanation.bookmakers as BookmakerExplanation[]) : [];
  const penalties = isRecord(explanation.penalties) ? explanation.penalties : {};
  const marketProbability = isRecord(explanation.market_probability) ? explanation.market_probability : {};
  const matchedEvent = isRecord(explanation.matched_event) ? explanation.matched_event : {};
  const explanationMarket = isRecord(explanation.market) ? explanation.market : {};
  const selectedBookmakers = Array.isArray(explanation.selected_bookmakers)
    ? explanation.selected_bookmakers.map(String)
    : bookmakers.map((book) => book.bookmaker).filter(Boolean).map(String);
  const matchedSelection = firstString(bookmakers.map((book) => book.selection)) ?? textFrom(explanationMarket.selection) ?? market.selection;
  const targetOutcome = firstString(bookmakers.map((book) => book.target_outcome)) ?? matchedSelection;
  const matchConfidence = numberFrom(matchedEvent.confidence_score);
  const marketSource = textFrom(marketProbability.source) ?? "n/a";
  const hasExplanation = Object.keys(explanation).length > 0;
  const rawSelection = textFrom(explanationMarket.raw_selection) ?? textFrom(explanationMarket.selection) ?? market.selection;
  const probabilityOrientation = textFrom(marketProbability.orientation);
  const isComplementedNoSelection = probabilityOrientation === "positive_yes_complemented_from_no";
  const displayOutcome = textFrom(explanationMarket.display_outcome) ?? textFrom(marketProbability.display_outcome) ?? targetOutcome;
  const isH2H = market.market_type === "h2h_game" || market.market_type === "h2h";

  return (
    <section className="border border-line bg-ink/70 p-4 sm:p-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-xs uppercase tracking-[0.16em] text-steel">Fair-Value Explanation</div>
          <h2 className="mt-2 text-xl font-semibold text-white">{textFrom(explanationMarket.event_name) ?? market.event_name}</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-steel">
            Nautilus compares the displayed prediction-market probability with a no-vig sportsbook consensus for the
            matched {isH2H ? "game and moneyline selection" : "category and selection"}. This is market-data analysis,
            not betting advice or trade execution.
          </p>
        </div>
        <div className="inline-flex items-center gap-2 border border-mint/30 bg-mint/10 px-3 py-2 text-sm text-mint">
          <CheckCircle2 className="h-4 w-4" />
          Audit view
        </div>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Fact label="Market YES probability" value={formatPercent(numberFrom(marketProbability.value ?? fairValue?.market_probability))} />
        <Fact label="Sportsbook fair" value={formatPercent(numberFrom(explanation.consensus_fair_probability ?? fairValue?.fair_probability))} />
        <Fact label="Gross edge" value={formatSignedPercent(numberFrom(explanation.gross_edge ?? fairValue?.gross_edge))} tone="white" />
        <Fact label="Net edge" value={formatSignedPercent(numberFrom(explanation.net_edge ?? fairValue?.net_edge))} tone="mint" />
        <Fact label="Liquidity" value={formatNumber(numberFrom(penalties.liquidity ?? fairValue?.liquidity))} />
        <Fact label="Spread" value={formatPercent(numberFrom(penalties.spread ?? fairValue?.spread))} />
        <Fact label="Confidence" value={formatPercent(numberFrom(explanation.confidence_score ?? fairValue?.confidence_score))} />
        <Fact label="Match confidence" value={formatPercent(matchConfidence)} />
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
        <div className="border border-line bg-panel/40 p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-steel">Matched Market</h3>
          <div className="mt-4 space-y-3 text-sm">
            <AuditRow label="Sportsbook category" value={textFrom(matchedEvent.event_name) ?? "n/a"} />
            <AuditRow label="Sportsbook selection" value={matchedSelection} />
            {isH2H ? <AuditRow label="Target team" value={textFrom(matchedEvent.target_team) ?? displayOutcome} /> : null}
            {isH2H ? <AuditRow label="Opponent" value={textFrom(matchedEvent.opponent) ?? "n/a"} /> : null}
            <AuditRow label="Outcome" value={`${displayOutcome} win`} />
            <AuditRow label="Raw contract side" value={rawSelection} />
            <AuditRow label="Prediction price source" value={marketSource} />
            <AuditRow label="Books used" value={selectedBookmakers.length > 0 ? selectedBookmakers.join(", ") : "n/a"} />
          </div>

          <div className="mt-4 border border-mint/25 bg-mint/10 p-3 text-sm leading-6 text-steel">
            <div className="font-medium text-mint">Why Nautilus accepts this match</div>
            <p className="mt-1">
              {textFrom(matchedEvent.reason) ??
                "The prediction title/category and selected outcome matched a sportsbook category and outcome above the configured confidence threshold."}
            </p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <MiniScore label="Category" value={numberFrom(matchedEvent.fuzzy_score)} />
              <MiniScore label="Outcome" value={numberFrom(matchedEvent.team_score)} />
              <MiniScore label="League" value={numberFrom(matchedEvent.league_score)} />
              <MiniScore label="Overall" value={matchConfidence} />
            </div>
          </div>
        </div>

        <div className="border border-line bg-panel/40 p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-steel">No-Vig Calculation</h3>
          <p className="mt-3 text-sm leading-6 text-steel">
            {isH2H
              ? "For H2H games, each book's moneyline outcomes are converted to implied probabilities and normalized so the game outcomes sum to 100%. Nautilus then applies bookmaker weights and averages the selected team's no-vig probabilities into the fair value."
              : "For outrights, each book's selected outcome probability is divided by the total implied probability of that sportsbook category. Nautilus then applies bookmaker weights and averages those no-vig probabilities into the fair value."}
            {isComplementedNoSelection
              ? " Because the raw prediction-market side is No, Nautilus displays one minus that market price so the main view stays oriented to the YES/winning outcome."
              : ""}
          </p>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[680px] text-sm">
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
                      No fair-value explanation has been written for this market yet.
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
                      <td className="px-3 py-3 text-right font-mono">{formatWeight(book.weight)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <Fact label="Spread penalty" value={formatPercent(numberFrom(penalties.spread_penalty))} />
            <Fact label="Liquidity penalty" value={formatPercent(numberFrom(penalties.liquidity_penalty))} />
            <Fact label="Consensus dispersion" value={formatPercent(numberFrom(explanation.consensus_dispersion))} />
          </div>
        </div>
      </div>

      <div className="mt-4 border border-amber/30 bg-amber/10 p-3 text-sm leading-6 text-amber">
        <div className="flex gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Nautilus surfaces pricing differences from live market data. It does not recommend wagers, place trades, or
            account for your personal constraints, execution risk, limits, taxes, or regulatory obligations.
          </p>
        </div>
      </div>

      <details className="mt-4 border border-line bg-panel/30 p-3">
        <summary className="cursor-pointer text-sm font-medium text-steel transition hover:text-white">
          Raw explanation debug data
        </summary>
        <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap border border-line bg-ink p-3 text-xs leading-5 text-steel">
          {hasExplanation ? JSON.stringify(explanation, null, 2) : "No explanation JSON available."}
        </pre>
      </details>
    </section>
  );
}

function Fact({
  label,
  value,
  tone = "white"
}: {
  label: string;
  value: string;
  tone?: "white" | "mint";
}) {
  return (
    <div className="border border-line bg-panel/50 p-3">
      <div className="text-xs uppercase tracking-[0.14em] text-steel">{label}</div>
      <div className={`mt-1 font-mono text-sm ${tone === "mint" ? "text-mint" : "text-white"}`}>{value}</div>
    </div>
  );
}

function AuditRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[150px_1fr] gap-3 border-b border-line/60 pb-2 last:border-b-0 last:pb-0">
      <div className="text-steel">{label}</div>
      <div className="text-white">{value}</div>
    </div>
  );
}

function MiniScore({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="border border-line/70 bg-ink/60 p-2">
      <div className="text-xs uppercase tracking-[0.12em] text-steel">{label}</div>
      <div className="mt-1 font-mono text-white">{formatPercent(value)}</div>
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function numberFrom(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function textFrom(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function firstString(values: Array<string | undefined>): string | null {
  return values.find((value) => typeof value === "string" && value.trim().length > 0) ?? null;
}

function formatNumber(value: number | null): string {
  if (value == null) {
    return "n/a";
  }
  return new Intl.NumberFormat("en", { maximumFractionDigits: 0 }).format(value);
}

function formatWeight(value: number | undefined): string {
  return typeof value === "number" ? value.toFixed(2).replace(/\.00$/, "") : "1";
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
