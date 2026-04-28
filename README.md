# Nautilus

Nautilus is a prediction-market fair-value scanner. It compares prediction-market prices from Polymarket and Kalshi with sportsbook odds, removes sportsbook vig, estimates fair probability, calculates edge, and shows opportunities in a clean research dashboard.

Nautilus is market data and analytics software. It is not financial advice, not betting advice, and not a trading or execution platform.

## Architecture

- `backend/`: FastAPI service, SQLAlchemy models, Alembic migrations, collector adapters, fair-value engine, and CLI jobs.
- `frontend/`: Next.js, TypeScript, Tailwind, and Recharts dashboard.
- `postgres`: Stores normalized markets, odds snapshots, fair-value snapshots, user model JSON, and alert rules.
- `docker-compose.yml`: Runs PostgreSQL, the FastAPI API, migrations, and the Next.js app.

## Run Locally

Create an environment file:

```bash
cp .env.example .env
```

Start the stack:

```bash
docker compose up --build
```

Open:

- Frontend: `http://localhost:3000`
- Backend health: `http://localhost:8000/health`
- API docs: `http://localhost:8000/docs`

The backend runs `alembic upgrade head` on container startup.

Frontend-only development:

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Backend-only API development:

```bash
cd backend
python -m pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Environment Variables

Required:

- `DATABASE_URL`: PostgreSQL URL, for example `postgresql+psycopg://nautilus:nautilus@postgres:5432/nautilus`.
- `FRONTEND_ORIGIN`: CORS origin for the Next.js app.

Optional data-source settings:

- `KALSHI_API_KEY`
- `KALSHI_API_SECRET`
- `THE_ODDS_API_KEY`
- `SPORTS_TO_COLLECT`, a comma-separated list such as `americanfootball_nfl,basketball_nba,baseball_mlb,icehockey_nhl`.
- `SPORTSBOOK_MARKETS_TO_COLLECT`, a comma-separated list of sportsbook market keys. Defaults to `h2h,outrights`. When `outrights` is enabled, Nautilus expands configured base sports with related active outright sport keys advertised by The Odds API, such as championship-winner markets, when available.
- `POLYMARKET_API_URL`
- `KALSHI_API_URL`
- `THE_ODDS_API_URL`

Optional Odds API quota email settings:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `ALERT_EMAIL_FROM`
- `ALERT_EMAIL_TO`
- `ODDS_API_LOW_QUOTA_THRESHOLD`, default `50`
- `ODDS_API_QUOTA_EMAIL_COOLDOWN_HOURS`, default `6`

Collectors are defensive: if a required key is missing, the job logs a clear skip message and exits without crashing the whole app.

## CLI Jobs

Run from inside the backend container:

```bash
docker compose exec backend python -m app.jobs.collect_prediction_markets
docker compose exec backend python -m app.jobs.collect_sportsbook_odds
docker compose exec backend python -m app.jobs.compute_fair_values
docker compose exec backend python -m app.jobs.send_alerts
```

For local backend development without Docker, install dependencies in `backend/`, set `DATABASE_URL`, then run the same `python -m ...` commands.

Run backend tests:

```bash
cd backend
python -m pytest tests
```

Exact collector commands:

```bash
# Polymarket public sports markets, no API key required.
docker compose exec backend python -m app.jobs.collect_prediction_markets

# The Odds API events plus h2h/outrights odds where supported. Requires THE_ODDS_API_KEY.
docker compose exec backend python -m app.jobs.collect_sportsbook_odds

# Limit sportsbook collection to selected sports.
docker compose exec -e SPORTS_TO_COLLECT=americanfootball_nfl,basketball_nba backend python -m app.jobs.collect_sportsbook_odds

# Limit sportsbook market collection to h2h only or request outrights explicitly.
docker compose exec -e SPORTSBOOK_MARKETS_TO_COLLECT=h2h backend python -m app.jobs.collect_sportsbook_odds
docker compose exec -e SPORTSBOOK_MARKETS_TO_COLLECT=h2h,outrights backend python -m app.jobs.collect_sportsbook_odds

# Compute fair values after snapshots are collected.
docker compose exec backend python -m app.jobs.compute_fair_values
```

For a conservative local loop:

```bash
./run_nautilus_live.sh
```

The loop collects Polymarket every 5 minutes, sportsbook odds every 1 hour by default, and computes fair values every 5 minutes.

## API Surface

- `GET /health`
- `GET /markets`
- `GET /markets/{id}`
- `GET /opportunities`: lightweight scanner rows only. The default response excludes raw provider payloads, market metadata JSON, user assumptions, and full explanation JSON.
- `GET /opportunities?include_debug=true`: adds assumptions and explanation JSON for debugging.
- `GET /opportunities?include_raw=true`: adds raw market metadata for debugging.
- `GET /opportunities/{market_id}`: detail response with explanation data for the selected market.
- `GET /opportunities/{market_id}/history`: lightweight time series for market YES probability, sportsbook fair probability, gross edge, net edge, and confidence.
- `GET /fair-values/latest`
- `POST /user-models`
- `GET /user-models`
- `POST /alerts`
- `GET /alerts`

## Fair-Value Methodology

Nautilus compares prediction-market prices with sportsbook-derived fair probabilities and surfaces possible pricing disagreements. It does not place trades, accept bets, hold funds, connect wallets, or provide personalized betting or financial advice.

1. Convert sportsbook American or decimal odds into implied probabilities.
2. For two-sided sportsbook markets, remove vig by normalizing both sides so their probabilities sum to 100%.
3. For futures and awards, use sportsbook `outrights` odds when available and remove vig by normalizing all outcomes in the outright market for each bookmaker.
4. Calculate prediction-market midpoint from bid/ask when both are available, otherwise from the best available price.
5. Orient futures, awards, and outright markets around the positive YES/winning outcome. If a raw Polymarket contract is stored as `No`, Nautilus displays and scores `1 - no_probability` as the market YES probability.
6. Calculate gross edge as `sportsbook_fair_probability_of_winning - prediction_market_yes_probability`.
7. Calculate spread and liquidity penalties.
8. Calculate net edge as `gross_edge - spread_penalty - liquidity_penalty`.
9. Calculate confidence from sportsbook count, spread quality, liquidity, and sportsbook consensus dispersion.

Supported fair-value routes:

- `h2h`: prediction-market H2H/game markets compared against sportsbook H2H moneyline odds.
- `futures`: team/championship/conference/division-style prediction markets compared against sportsbook `outrights` odds when The Odds API returns matching outcomes.
- `awards`: player award markets compared against sportsbook `outrights` odds when The Odds API returns matching award outcomes.

The scanner and detail UI use this same orientation:

- H2H rows show the selected team/outcome probability.
- Futures/awards/outrights rows show `Market YES` for the named team/player/outcome winning.
- `Sportsbook Fair` is the no-vig sportsbook probability for that same winning outcome.
- Raw YES/NO contract side and provider payloads remain available only in detail/debug views.

Plain-English interpretation:

- A binary YES contract pays $1 if the event happens and $0 if it does not. A YES price of `$0.04` roughly implies a 4% market probability.
- American positive odds use `100 / (odds + 100)`, so `+400` implies 20%.
- American negative odds use `abs(odds) / (abs(odds) + 100)`, so `-150` implies 60%.
- Decimal odds use `1 / decimal_odds`, so `5.00` implies 20%.
- Sportsbooks include margin/vig. If two raw sides are 58% and 48%, the total is 106%; no-vig normalizes them to 54.7% and 45.3%.
- `Net Edge = Sportsbook Fair Probability - Prediction-Market YES Probability`, adjusted for penalties where applicable.
- Positive Net Edge is shown as possible YES underpricing relative to sportsbook fair value.
- Negative Net Edge is shown as possible YES overpricing relative to sportsbook fair value.
- A YES contract priced at 3.9% costs about `$0.039` per `$1` payout. If sportsbook no-vig fair probability is 5.4%, theoretical EV is approximately `0.054 - 0.039 = $0.015` per `$1` payout contract. This is not guaranteed profit and can be wrong because of liquidity, fees, stale data, settlement differences, or matching/model error.

Limitations:

- Nautilus does not fake futures or award odds. If The Odds API does not return `outrights` for the configured sport, related outright sport key, region, or account plan, futures/awards markets are skipped with a clear log message.
- The Odds API exposes `outrights` only for selected sports/competitions. Availability can differ from H2H game odds and may not be present on every plan or region.
- Futures/awards matching is conservative: team futures require strong team-name matches, player awards require strong player-name matches, and weak or ambiguous matches are skipped.

Current and future market modes:

- Current Nautilus mode is futures/outrights research.
- Future H2H/live-game mode would match prediction-market game contracts to sportsbook H2H/moneyline odds. That requires game-level prediction markets, team extraction, start-time matching, and faster odds polling.

## Odds API Quota Monitoring

The Odds API free quota is limited. Nautilus captures these response headers when present:

- `x-requests-remaining`
- `x-requests-used`
- `x-requests-last`

The collector logs quota usage without printing the API key. If remaining quota falls below `ODDS_API_LOW_QUOTA_THRESHOLD`, if HTTP `429 Too Many Requests` occurs, or if `OUT_OF_USAGE_CREDITS` appears in the API response, Nautilus can send a quota warning email through the SMTP settings above. Email warnings are rate-limited by `ODDS_API_QUOTA_EMAIL_COOLDOWN_HOURS` using a small local state file.

Recommended conservative polling:

- Polymarket: every 5 minutes
- Sportsbook odds: every 1-2 hours for futures/outrights
- Fair-value computation: every 5 minutes

When sportsbook collection is unavailable because quota is exhausted, the live loop continues: it collects prediction markets, skips or fails sportsbook refresh safely, and recomputes fair values using the latest stored sportsbook odds.

Each `fair_value_snapshots` row stores an `explanation_json` object with selected bookmakers, original odds, implied probabilities, no-vig probabilities, consensus fair probability, market probability source, gross edge, penalties, net edge, event-match confidence, and final confidence score.

Fair-value snapshots are append-only, so repeated `compute_fair_values` runs create a history of signal quality over time. The history endpoint intentionally omits raw provider blobs, assumptions, and explanation JSON.

User models are stored as JSON configuration only. Nautilus does not execute user-provided Python code.

## Database Tables

The initial Alembic migration creates:

- `markets`
- `prediction_market_snapshots`
- `sportsbook_events`
- `sportsbook_odds_snapshots`
- `fair_value_snapshots`
- `user_models`
- `alert_rules`

## Notes

The included collectors are clean adapters around external APIs and intentionally normalize into internal DTOs before database writes. Raw provider payloads are stored in JSONB columns on event metadata and snapshot rows, while market/event rows are upserted and snapshots remain append-only. You can extend the adapters with pagination, market filters, and richer sports mappings without changing the API or frontend contracts.
