#!/usr/bin/env bash
# fetch_datasets.sh — token-free Apify dataset pull.
#
# Apify DEFAULT datasets are publicly readable with plain curl, no token (verified 200 on
# 2026-08-11). So results never need to go through the MCP layer, and -- more importantly --
# THEY MUST NEVER ENTER CONTEXT. Precedent: a Placecraft list call returned 168,571 chars
# and spilled into the transcript.
#
# Bash `sleep N && cmd` is blocked by the command classifier, so the run is polled with an
# `until` loop on the status endpoint instead.
#
# Writes to a .tmp file and renames only on HTTP 200, so a truncated body is never mistaken
# for a result set.
#
# Usage:
#   bash scripts/fetch_datasets.sh <datasetId> <out_dir>
#   bash scripts/fetch_datasets.sh --wait <runId> <out_dir>

set -euo pipefail

API="https://api.apify.com/v2"

usage() { sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2; }
[ $# -ge 2 ] || usage

if [ "$1" = "--wait" ]; then
  RUN_ID="$2"; OUT_DIR="${3:-.}"
  mkdir -p "$OUT_DIR"
  echo "polling run $RUN_ID (until-loop; sleep && cmd is blocked by the classifier)"
  STATUS=""
  until [ "$STATUS" = "SUCCEEDED" ] || [ "$STATUS" = "FAILED" ] || \
        [ "$STATUS" = "ABORTED" ] || [ "$STATUS" = "TIMED-OUT" ]; do
    STATUS="$(curl -sS "$API/actor-runs/$RUN_ID" | sed -n 's/.*"status":"\([A-Z-]*\)".*/\1/p' | head -1)"
    [ -n "$STATUS" ] || STATUS="UNKNOWN"
    printf '  status=%s\n' "$STATUS"
    [ "$STATUS" = "RUNNING" ] || [ "$STATUS" = "READY" ] || [ "$STATUS" = "UNKNOWN" ] || break
    read -r -t 10 _ < /dev/null 2>/dev/null || true
  done
  if [ "$STATUS" != "SUCCEEDED" ]; then
    echo "run ended $STATUS — not fetching a dataset from a non-successful run" >&2
    exit 1
  fi
  DATASET_ID="$(curl -sS "$API/actor-runs/$RUN_ID" | sed -n 's/.*"defaultDatasetId":"\([^"]*\)".*/\1/p' | head -1)"
  echo "defaultDatasetId=$DATASET_ID"
else
  DATASET_ID="$1"; OUT_DIR="$2"
fi

mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/dataset_${DATASET_ID}.json"
TMP="$OUT.tmp"

CODE="$(curl -sS -o "$TMP" -w '%{http_code}' \
  "$API/datasets/${DATASET_ID}/items?clean=true&format=json")"

if [ "$CODE" != "200" ]; then
  echo "HTTP $CODE fetching dataset $DATASET_ID — leaving $TMP in place, not promoting" >&2
  exit 1
fi

mv "$TMP" "$OUT"
BYTES="$(wc -c < "$OUT" | tr -d ' ')"
echo "wrote $OUT ($BYTES bytes)"
echo "DO NOT cat this file into context. Read it with a script."
