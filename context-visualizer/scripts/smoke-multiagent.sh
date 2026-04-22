#!/usr/bin/env bash
# Multi-agent + tool-use smoke test for the workspace view.
#
# Drives the claude CLI through the Flask LLM-dispatch bridge with a mix
# of single-agent tool use, hierarchical session IDs (so the adapter
# groups them into one conversation), and prompts that force multiple
# turns. Exists because the original deploy/ scripts under
# context-exploration-engine/agent-interceptor/ assume the legacy
# port-9090 standalone proxy; the current architecture routes through
# Flask on 5000.
#
# Usage (from anywhere, on ares-comp-11, with dt_demo_server + Flask up):
#   bash context-visualizer/scripts/smoke-multiagent.sh
#
# Env overrides:
#   DTP_HOST     default: ares-comp-11
#   DTP_PORT     default: 5000
#   DTP_PREFIX   default: smoke-$(date +%s)   (unique per run so runs don't collide)
#   DTP_SKIP     comma-separated test ids to skip: basic, multiturn, tools, fanout

set -euo pipefail

HOST="${DTP_HOST:-ares-comp-11}"
PORT="${DTP_PORT:-5000}"
PREFIX="${DTP_PREFIX:-smoke-$(date +%s)}"
SKIP="${DTP_SKIP:-}"

BASE_URL="http://${HOST}:${PORT}"

# ── preflight ──────────────────────────────────────────────────────────────
need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' not on PATH" >&2; exit 1; }; }
need claude
need curl

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY not set. Try:" >&2
  echo "  export ANTHROPIC_API_KEY=\$(cat ~/.anthropic_key)" >&2
  exit 1
fi

# Flask on :5000 must not be proxied via Squid; set no_proxy if it isn't.
export no_proxy="${no_proxy:-localhost,127.0.0.1,ares-comp-11,ares}"
export NO_PROXY="${NO_PROXY:-$no_proxy}"

echo "── checking Flask dispatch endpoint ─────────────────────────────"
if ! curl -fsS --noproxy '*' --max-time 5 "${BASE_URL}/api/conversations" >/dev/null; then
  echo "ERROR: Flask at ${BASE_URL} is not responding to /api/conversations." >&2
  echo "Start it in Terminal B (see docs/setup-guide.md)." >&2
  exit 1
fi
echo "  OK: ${BASE_URL} reachable"
echo

skip() { [[ ",$SKIP," == *",$1,"* ]]; }

run() {
  local sess="$1" prompt="$2" turns="${3:-3}"
  local url="${BASE_URL}/_session/${sess}"
  echo "── [${sess}] ${prompt:0:60}..."
  ANTHROPIC_BASE_URL="$url" claude \
    --permission-mode bypassPermissions \
    --max-turns "$turns" \
    -p "$prompt" 2>&1 | sed 's/^/    /'
  echo
}

# ── test 1: basic, no tools (sanity: the pipeline still works) ─────────────
if ! skip basic; then
  echo "=== TEST 1: basic agent, no tools ==="
  run "${PREFIX}-basic" "What is 2+2? Reply with only the number." 1
fi

# ── test 2: Bash tool, multiple turns in one session ───────────────────────
if ! skip multiturn; then
  echo "=== TEST 2: Bash tool, multi-turn ==="
  run "${PREFIX}-bash" \
    "Use the Bash tool to list the contents of /tmp (just 'ls /tmp'). Then report how many entries you see." \
    5
fi

# ── test 3: Read + Bash chained (two different tools, several turns) ───────
if ! skip tools; then
  echo "=== TEST 3: Read + Bash chained ==="
  run "${PREFIX}-tools" \
    "Use Bash to run 'hostname', then use Read to read /etc/os-release, then summarize the OS and hostname in one sentence." \
    6
fi

# ── test 4: fan-out — orchestrator + two subagents (explicit hierarchical ids)
# The adapter groups sessions by the portion before the first '.', so
# X, X.1, X.2 collapse into one conversation row with three graph nodes.
if ! skip fanout; then
  echo "=== TEST 4: fan-out orchestrator + 2 subagents ==="
  run "${PREFIX}-fanout" \
    "You are a trip-planning orchestrator. In one short paragraph, describe a research plan for recommending a 2-day Barcelona itinerary. Do not use any tools." \
    1
  run "${PREFIX}-fanout.1" \
    "Use Bash to run 'date' and include the current timestamp in your answer. Then propose 3 must-see sights in Barcelona." \
    3
  run "${PREFIX}-fanout.2" \
    "Use Bash to run 'uptime'. Then suggest 2 tapas bars in Barcelona." \
    3
fi

# ── report back: what the adapter now sees ─────────────────────────────────
echo "── verifying workspace API picked up the runs ───────────────────"
curl -s --noproxy '*' "${BASE_URL}/api/conversations" \
  | python3 -c 'import json,sys
data=json.load(sys.stdin)
mine=[c for c in data if c.get("id","").startswith("'"${PREFIX}"'")]
print(f"  {len(mine)} conversation(s) matching prefix '"${PREFIX}"':")
for c in mine:
    print(f"    {c.get(\"id\")}: lastTurn={c.get(\"lastTurn\",\"-\")} tokens={c.get(\"totalTokens\",\"-\")}")'

echo
echo "Open http://127.0.0.1:${PORT}/workspace (via your laptop tunnel) and"
echo "look for rows starting with '${PREFIX}-'. The fan-out test should"
echo "appear as ONE row '${PREFIX}-fanout' with 3 nodes in the graph."
