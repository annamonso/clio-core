#!/usr/bin/env bash
# Chained driver: A -> B -> C -> analyze.
# Stops the chain immediately if any sweep returns RC_CHAIN_ABORT (=2):
#   - 2 of last 3 runs failed in a sweep, OR
#   - a run completed with interaction_count=0 on both agents (contamination).
# Other non-zero exit codes (sweep had some failures, but data is usable) do
# NOT stop the chain — we still proceed to the next sweep and analyze.
set -u
cd "$(dirname "$0")"

export LEADER_HOST=ares-comp-12
export LEADER_PORT=5050
export LEADER_JOB=12512
export PEER_HOST=ares-comp-13
export PEER_JOB=12512
export ANTHROPIC_API_KEY="$(cat "$HOME/.anthropic_key")"
export PYTHONUNBUFFERED=1   # make all child python output line-buffered

LOG=/tmp/bench_demo6_chain.log
: > "$LOG"

stamp() { date '+%Y-%m-%dT%H:%M:%S'; }
RC_CHAIN_ABORT=2

{
  echo "=== bench_demo6 chain start: $(stamp) ==="
  echo "    leader=$LEADER_HOST:$LEADER_PORT  peer=$PEER_HOST  job=$LEADER_JOB"
  echo "    live tail: tail -f $LOG"
  echo

  aborted=0
  for sweep in a b c; do
    if [ "$aborted" = "1" ]; then
      echo "=== Sweep $sweep skipped (chain aborted earlier) ==="
      echo
      continue
    fi
    echo "=== Sweep $sweep start: $(stamp) ==="
    python3 -u bench.py "$sweep"
    rc=$?
    echo "=== Sweep $sweep done: $(stamp), exit=$rc ==="
    echo
    if [ "$rc" = "$RC_CHAIN_ABORT" ]; then
      aborted=1
    fi
  done

  echo "=== analyze start: $(stamp) ==="
  python3 -u bench.py analyze
  echo "=== analyze done: $(stamp) ==="
  if [ "$aborted" = "1" ]; then
    echo "=== CHAIN ABORTED EARLY — see SUMMARY.md for partial-run analysis ==="
  else
    echo "=== ALL DONE: $(stamp) ==="
  fi
} 2>&1 | tee "$LOG"
