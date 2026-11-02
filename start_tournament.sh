#!/usr/bin/env bash
# Run the tournament continuously in this terminal. Ctrl+C is safe: every
# completed secret pair is already checkpointed and the next run resumes it.
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m digitcode.tournament \
  --games 500 \
  --pairs 250 \
  --checkpoint "Digitcode/benchmarks/dg1-dg2-500.json"
