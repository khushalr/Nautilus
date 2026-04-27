#!/bin/bash

echo "Running Nautilus data cycle at $(date)"

docker compose exec backend python -m app.jobs.collect_prediction_markets
docker compose exec backend python -m app.jobs.collect_sportsbook_odds
docker compose exec backend python -m app.jobs.compute_fair_values

echo "Finished Nautilus data cycle at $(date)"

