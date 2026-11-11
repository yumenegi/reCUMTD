#!/usr/bin/env bash
# Sync data/ with the Hugging Face dataset hikarinko/cumtd.
# Downloads only new or changed snapshots and GTFS zips; skips the live mtd.sqlite.
set -euo pipefail

cd "$(dirname "$0")"

uvx --from huggingface_hub hf download hikarinko/cumtd --repo-type dataset \
  --include "snapshots/*" --include "gtfs/*" \
  --local-dir data "$@"

latest=$(ls -1 data/snapshots/mtd-*.sqlite 2>/dev/null | sort | tail -n 1 || true)
echo "latest snapshot: ${latest:-none}"
