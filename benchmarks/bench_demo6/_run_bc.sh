#!/usr/bin/env bash
# Continuation chain: cycle services -> Sweep B -> cycle services -> Sweep C -> analyze.
# Cycling between sweeps works around Werkzeug's tendency to back up under
# sustained streaming load. Per-scenario JSONs are written immediately during
# each run so cycling does NOT lose data — analyze reads runs.jsonl + per-run
# JSONs, never /api/scenarios.
set -u
cd "$(dirname "$0")"

export LEADER_HOST=ares-comp-12
export LEADER_PORT=5050
export LEADER_JOB=12512
export PEER_HOST=ares-comp-13
export PEER_JOB=12512
export ANTHROPIC_API_KEY="$(cat "$HOME/.anthropic_key")"
export PYTHONUNBUFFERED=1

LOG=/tmp/bench_demo6_chain.log
: > "$LOG"

stamp() { date '+%Y-%m-%dT%H:%M:%S'; }

cycle_services() {
  echo "--- cycle services on $LEADER_HOST ---"
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no "$LEADER_HOST" \
    "bash $(pwd)/_bringup.sh" 2>&1 | tail -5
  sleep 2
}

{
  echo "=== B+C chain start: $(stamp) ==="
  echo "    leader=$LEADER_HOST:$LEADER_PORT  peer=$PEER_HOST  job=$LEADER_JOB"
  echo

  cycle_services
  echo
  echo "=== Sweep b start: $(stamp) ==="
  python3 -u bench.py b
  rc_b=$?
  echo "=== Sweep b done: $(stamp), exit=$rc_b ==="
  echo

  cycle_services
  echo
  echo "=== Sweep c start: $(stamp) ==="
  python3 -u bench.py c
  rc_c=$?
  echo "=== Sweep c done: $(stamp), exit=$rc_c ==="
  echo

  echo "=== analyze start: $(stamp) ==="
  python3 -u bench.py analyze
  echo "=== analyze done: $(stamp) ==="
  echo "=== ALL DONE: $(stamp) (sweep_b_rc=$rc_b sweep_c_rc=$rc_c) ==="
} 2>&1 | tee "$LOG"
