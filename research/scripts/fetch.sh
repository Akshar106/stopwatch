#!/usr/bin/env bash
# Pull public job-board data used in docs/01-market-research.md (snapshot: 2026-10-18).
# Usage: research/scripts/fetch.sh <out_dir>
set -euo pipefail
OUT=${1:?out dir}; mkdir -p "$OUT/amzn"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"
for c in stripe airbnb databricks datadog cloudflare robinhood coinbase dropbox pinterest lyft figma discord reddit \
         twilio instacart roblox gitlab mongodb elastic okta affirm samsara asana duolingo brex squarespace block; do
  curl -s --max-time 30 -o "$OUT/gh_$c.json" "https://boards-api.greenhouse.io/v1/boards/$c/jobs?content=true"
done
for o in notion ramp openai linear plaid snowflake; do
  curl -s --max-time 30 -o "$OUT/ash_$o.json" "https://api.ashbyhq.com/posting-api/job-board/$o?includeCompensation=true"
done
curl -s --max-time 30 -o "$OUT/lev_palantir.json" "https://api.lever.co/v0/postings/palantir?mode=json"
for off in $(seq 0 100 1200); do
  curl -s -A "$UA" --max-time 40 -o "$OUT/amzn/p_$off.json" \
    "https://www.amazon.jobs/en/search.json?base_query=software%20development%20engineer&loc_query=United%20States&country=USA&result_limit=100&offset=$off&sort=recent"
done
# Then: python3 -I load.py <out_dir> all.json && python3 -I filter.py all.json early.json && python3 -I analyze.py early.json sample.csv
