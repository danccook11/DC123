#!/usr/bin/env bash
# freeze.sh — step 1 of Quick start, not a caveat.
#
# Snapshots the skill out of any synced tree before a run, and prints the snapshot path and
# hash for the run manifest. Every subsequent stage runs from the SNAPSHOT, not from the
# working copy.
#
# Why this is step 1: a mid-run iCloud sync half-wrote `zoning_flu.py` during the Davenport
# run. Two synced roots (OneDrive and iCloud) drift against each other, and iCloud corrupts
# partial writes. A run that reads its own scripts from a syncing directory can change
# underneath itself between stages.
#
# Usage:
#   bash scripts/freeze.sh                    # snapshot to <cache_root>/skill_snapshots/<runid>
#   bash scripts/freeze.sh --run-id my_run    # explicit run id
#   eval "$(bash scripts/freeze.sh --export)" # set RUN_SKILL_DIR in the calling shell

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID=""
EXPORT_MODE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --run-id) RUN_ID="${2:-}"; shift 2 ;;
    --export) EXPORT_MODE=1; shift ;;
    -h|--help)
      sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Cache root resolution mirrors octlib.cache_root() exactly. Keep them in step.
if [ -n "${OWNER_TRACE_CACHE:-}" ]; then
  CACHE_ROOT="$OWNER_TRACE_CACHE"
elif [ -d "$HOME/Library/Caches" ]; then
  CACHE_ROOT="$HOME/Library/Caches/claude-owner-enrich"
elif [ -n "${XDG_CACHE_HOME:-}" ]; then
  CACHE_ROOT="$XDG_CACHE_HOME/claude-owner-enrich"
else
  CACHE_ROOT="$HOME/.cache/claude-owner-enrich"
fi

[ -n "$RUN_ID" ] || RUN_ID="$(date -u +%Y%m%d-%H%M%S)"
SNAP="$CACHE_ROOT/skill_snapshots/$RUN_ID"

# Force iCloud to materialize any dataless placeholder files before copying. Without this a
# .icloud stub copies as a zero-byte file and the run silently loses a script.
if command -v brctl >/dev/null 2>&1; then
  brctl download "$SKILL_DIR" >/dev/null 2>&1 || true
fi

mkdir -p "$SNAP"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git' --exclude '__pycache__' --exclude '.pytest_cache' \
    --exclude '*.pyc' --exclude '.DS_Store' \
    "$SKILL_DIR"/ "$SNAP"/
else
  # BSD/GNU cp fallback. rsync is present on macOS, but do not assume it on a runner.
  rm -rf "${SNAP:?}"/* 2>/dev/null || true
  (cd "$SKILL_DIR" && tar cf - \
      --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' \
      --exclude='*.pyc' --exclude='.DS_Store' .) | (cd "$SNAP" && tar xf -)
fi

# Content hash over the snapshot, stable across machines: sorted relative paths, each
# file's sha256, hashed together. Goes into the run manifest so a deliverable can be tied
# to the exact code that produced it.
HASH="$(cd "$SNAP" && find . -type f ! -path './.git/*' -print0 \
  | LC_ALL=C sort -z \
  | xargs -0 shasum -a 256 2>/dev/null \
  | shasum -a 256 | cut -d' ' -f1)"

if [ "$EXPORT_MODE" = "1" ]; then
  echo "export RUN_SKILL_DIR='$SNAP'"
  echo "export RUN_SKILL_HASH='$HASH'"
  echo "export OWNER_TRACE_CACHE_ROOT='$CACHE_ROOT'"
  exit 0
fi

cat <<EOF
freeze: snapshot complete
  RUN_SKILL_DIR   $SNAP
  RUN_SKILL_HASH  $HASH
  cache root      $CACHE_ROOT

Run every stage from RUN_SKILL_DIR, and record RUN_SKILL_HASH in the run manifest.
Intermediates, fixtures, caches and the ledger stay under the cache root — never in a
synced tree, because CENSUS.json / HUMANS.json / phone_verdicts.json carry names, home
addresses, phones and deceased flags.
EOF
