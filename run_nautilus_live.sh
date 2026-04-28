#!/bin/bash

# Nautilus live research loop.
#
# Polymarket is collected frequently because prediction-market prices can move quickly.
# Sportsbook odds are collected less often because The Odds API is quota-limited, futures/outrights
# generally move slower, and fair values can still update from Polymarket movement using the latest
# stored sportsbook snapshot.

PREDICTION_INTERVAL_SECONDS="${PREDICTION_INTERVAL_SECONDS:-300}"      # 5 minutes
SPORTSBOOK_INTERVAL_SECONDS="${SPORTSBOOK_INTERVAL_SECONDS:-3600}"    # 1 hour

last_sportsbook_run=0
last_sportsbook_status="not run yet"

redact() {
  sed -E 's/apiKey=[A-Za-z0-9_-]+/apiKey=REDACTED/g; s/(THE_ODDS_API_KEY=)[^[:space:]]+/\1REDACTED/g; s/(ODDS_API_KEY=)[^[:space:]]+/\1REDACTED/g'
}

run_and_capture() {
  command_name="$1"
  shift

  echo ""
  echo "----- Running: $command_name at $(date -u +"%Y-%m-%dT%H:%M:%SZ") -----"

  output=$("$@" 2>&1)
  exit_code=$?
  safe_output=$(printf "%s" "$output" | redact)
  printf "%s\n" "$safe_output"

  RUN_OUTPUT="$safe_output"
  return $exit_code
}

extract_prediction_count() {
  printf "%s" "$1" | sed -nE 's/.*Stored ([0-9]+) prediction-market snapshots.*/\1/p' | tail -1
}

extract_sportsbook_count() {
  printf "%s" "$1" | sed -nE 's/.*Stored ([0-9]+) sportsbook odds snapshots.*/\1/p' | tail -1
}

extract_fair_value_count() {
  printf "%s" "$1" | sed -nE 's/.*Computed ([0-9]+) fair values.*/\1/p' | tail -1
}

is_quota_failure() {
  printf "%s" "$1" | grep -E "429 Too Many Requests|OUT_OF_USAGE_CREDITS|quota/rate limit|quota exhausted|low quota|requests remaining=0|remaining=0" >/dev/null
}

echo "Starting Nautilus live loop at $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "Polymarket interval: ${PREDICTION_INTERVAL_SECONDS}s"
echo "Sportsbook interval: ${SPORTSBOOK_INTERVAL_SECONDS}s"
echo "Press Control+C to stop."

while true; do
  now=$(date +%s)
  cycle_started=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  prediction_summary="not run"
  sportsbook_summary="skipped"
  fair_value_summary="not run"

  echo ""
  echo "=============================="
  echo "Nautilus cycle started at ${cycle_started}"
  echo "=============================="

  run_and_capture "prediction markets" docker compose exec -T backend python -m app.jobs.collect_prediction_markets
  prediction_count=$(extract_prediction_count "$RUN_OUTPUT")
  prediction_summary="${prediction_count:-unknown} snapshots"

  if [ $((now - last_sportsbook_run)) -ge "$SPORTSBOOK_INTERVAL_SECONDS" ]; then
    if run_and_capture "sportsbook odds" docker compose exec -T backend python -m app.jobs.collect_sportsbook_odds; then
      if is_quota_failure "$RUN_OUTPUT"; then
        sportsbook_summary="quota unavailable; using latest stored sportsbook odds"
        echo "Sportsbook odds unavailable/quota exhausted; using latest stored sportsbook odds for fair-value computation."
      else
        sportsbook_count=$(extract_sportsbook_count "$RUN_OUTPUT")
        sportsbook_summary="ran: ${sportsbook_count:-unknown} snapshots"
        last_sportsbook_run=$now
      fi
      last_sportsbook_status="$sportsbook_summary"
    else
      if is_quota_failure "$RUN_OUTPUT"; then
        sportsbook_summary="quota unavailable; using latest stored sportsbook odds"
        echo "Sportsbook odds unavailable/quota exhausted; using latest stored sportsbook odds for fair-value computation."
      else
        sportsbook_summary="failed; using latest stored sportsbook odds"
      fi
      last_sportsbook_status="$sportsbook_summary"
    fi
  else
    sportsbook_summary="skipped to preserve quota; last status: ${last_sportsbook_status}"
    echo "Skipping sportsbook odds this cycle to preserve API quota."
    echo "Sportsbook odds unavailable/quota exhausted; using latest stored sportsbook odds for fair-value computation."
  fi

  run_and_capture "fair values" docker compose exec -T backend python -m app.jobs.compute_fair_values
  fair_value_count=$(extract_fair_value_count "$RUN_OUTPUT")
  fair_value_summary="${fair_value_count:-unknown} computed"

  echo ""
  echo "Cycle summary"
  echo "timestamp=${cycle_started}"
  echo "prediction_markets=${prediction_summary}"
  echo "sportsbook_collection=${sportsbook_summary}"
  echo "fair_values=${fair_value_summary}"
  echo "Sleeping for ${PREDICTION_INTERVAL_SECONDS}s..."

  sleep "$PREDICTION_INTERVAL_SECONDS"
done
