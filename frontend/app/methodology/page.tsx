import type { ReactNode } from "react";

export default function MethodologyPage() {
  return (
    <div className="space-y-6">
      <section className="border border-line bg-ink/70 p-5">
        <div className="text-xs uppercase tracking-[0.18em] text-steel">Methodology</div>
        <h1 className="mt-2 text-2xl font-semibold text-white">How Nautilus Reads Pricing Disagreements</h1>
        <p className="mt-3 max-w-4xl text-sm leading-6 text-steel">
          Nautilus compares prediction-market prices with sportsbook-derived fair probabilities and surfaces possible
          pricing disagreements. It does not place trades, accept bets, hold funds, or provide personalized betting or
          financial advice.
        </p>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Panel title="Prediction-Market Prices As Probabilities">
          <p>
            A binary YES contract pays $1 if the event happens and $0 if it does not. A YES price of $0.04 therefore
            roughly implies a 4% market probability. For futures and outrights, Nautilus displays the positive
            YES/winning probability for the named team, player, or outcome.
          </p>
        </Panel>
        <Panel title="Converting Odds To Implied Probability">
          <p>American odds become implied probabilities with two formulas:</p>
          <ul className="mt-3 space-y-2">
            <li>Positive odds: `100 / (odds + 100)`. Example: `+400` is `100 / 500 = 20%`.</li>
            <li>Negative odds: `abs(odds) / (abs(odds) + 100)`. Example: `-150` is `150 / 250 = 60%`.</li>
            <li>Decimal odds: `1 / decimal_odds`. Example: `5.00` is `20%`.</li>
          </ul>
        </Panel>
        <Panel title="No-Vig Fair Probability">
          <p>
            Sportsbooks include margin, often called vig, so raw implied probabilities usually sum to more than 100%.
            If Team A is 58% and Team B is 48%, the total is 106%. No-vig normalization divides each side by the total:
            Team A becomes `58 / 106 = 54.7%`, and Team B becomes `48 / 106 = 45.3%`.
          </p>
          <p className="mt-3">
            Nautilus removes vig because comparing prediction-market prices to raw sportsbook implied probabilities
            would overstate fair value. No-vig probability is a cleaner sportsbook-implied benchmark.
          </p>
        </Panel>
        <Panel title="Net Edge">
          <p>
            Net Edge is `Sportsbook Fair Probability - Prediction-Market YES Probability`, adjusted for spread and
            liquidity penalties where applicable. Positive Net Edge means YES may be underpriced relative to sportsbook
            fair value. Negative Net Edge means YES may be overpriced relative to sportsbook fair value.
          </p>
          <p className="mt-3">
            Nautilus uses neutral language: possible YES underpricing, possible YES overpricing, pricing disagreement,
            and market-data signal.
          </p>
        </Panel>
        <Panel title="Money Interpretation">
          <p>
            A prediction-market YES contract priced at 3.9% costs about $0.039 per $1 payout. If sportsbook no-vig fair
            probability is 5.4%, theoretical EV is approximately `0.054 - 0.039 = $0.015` per $1 payout contract.
          </p>
          <p className="mt-3">
            This is not guaranteed profit. It can be wrong because of market disagreement, liquidity, fees, settlement
            differences, stale data, or model and matching error.
          </p>
        </Panel>
        <Panel title="Research, Not Instructions">
          <p>
            Nautilus does not provide instructions for real-world execution. If a user independently trusts sportsbook
            fair value more than the prediction-market price, a positive Net Edge may suggest the YES contract is lower
            than that external benchmark. Nautilus remains research and analytics software.
          </p>
        </Panel>
        <Panel title="Historical Signals">
          <p>
            A historical signal is a timestamp where reconstructed Market YES, Sportsbook Fair, confidence, match
            confidence, and liquidity pass the configured research thresholds. Positive Net Edge is labeled possible YES
            underpricing. Negative Net Edge is tracked as possible YES overpricing.
          </p>
        </Panel>
        <Panel title="Paper-Trade Simulation">
          <p>
            Nautilus can simulate a hypothetical long-YES paper position for positive-edge signals because the research
            question is whether Market YES later moved toward the sportsbook-derived benchmark. Negative-edge signals
            are tracked, but the default simulation does not model short exposure.
          </p>
          <p className="mt-3">
            Paper P&L per $1 payout contract is `future Market YES - entry Market YES`. Return on stake is that paper
            P&L divided by the entry Market YES price.
          </p>
        </Panel>
        <Panel title="Performance Metrics">
          <p>
            Edge closing means the later edge moved closer to zero. Market moved expected direction means Market YES
            increased after a positive-edge signal. Paper P&L measures only the hypothetical price change in the
            simulated position.
          </p>
        </Panel>
        <Panel title="Backtest Limitations">
          <p>
            Historical data may be sparse, displayed prices may not have been available at meaningful size, and
            fees, spreads, liquidity, stale data, settlement differences, and sportsbook benchmark error can materially
            change results. Nautilus does not simulate execution or slippage yet.
          </p>
        </Panel>
      </section>

      <section className="border border-line bg-ink/70 p-5">
        <div className="text-xs uppercase tracking-[0.16em] text-steel">Market Coverage</div>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <div>
            <h2 className="text-lg font-semibold text-white">Current mode: futures and outrights</h2>
            <p className="mt-2 text-sm leading-6 text-steel">
              Nautilus currently focuses on Polymarket sports futures and awards matched to sportsbook `outrights`
              markets when The Odds API provides matching categories and selections.
            </p>
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">Future mode: H2H/live games</h2>
            <p className="mt-2 text-sm leading-6 text-steel">
              Future H2H support would match prediction-market game contracts to sportsbook moneyline odds. That
              requires game-level prediction markets, team extraction, start-time matching, and faster odds polling.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border border-line bg-ink/70 p-5">
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <div className="mt-3 text-sm leading-6 text-steel">{children}</div>
    </section>
  );
}
