#!/usr/bin/env bash
# Multi-agent peer smoke test: two independent agents, two hosts, one scenario.
#
# Simulates the Phase 1 cross-node feature without needing a real SLURM
# allocation: we pretend we're on two different hosts by spoofing the
# X-Agent-Host header on each request and directly POSTing a pair of
# inter-agent start/done events to the leader's ingest endpoint.
#
# For a real two-node run (salloc -N 2), set DTP_REAL_NODES=1 and the script
# will srun each agent onto its allocated node instead of spoofing the host.
#
# Env overrides:
#   DTP_LEADER_HOST   default: ares-comp-11
#   DTP_LEADER_PORT   default: 5000
#   DTP_SCENARIO      default: peer-smoke-$(date +%s)
#   DTP_REAL_NODES    default: 0 (1 = use srun to land agents on separate nodes)
#   DTP_HOSTS         comma-separated list of two hosts; default: ares-comp-11,ares-comp-12
#
# Requires: claude, curl, jq (optional, for readable JSON summaries).

set -euo pipefail

HOST="${DTP_LEADER_HOST:-ares-comp-11}"
PORT="${DTP_LEADER_PORT:-5000}"
SCENARIO="${DTP_SCENARIO:-peer-smoke-$(date +%s)}"
REAL_NODES="${DTP_REAL_NODES:-0}"
IFS=',' read -r HOST_A HOST_B <<< "${DTP_HOSTS:-ares-comp-11,ares-comp-12}"

BASE_URL="http://${HOST}:${PORT}"
SESSION_A="planner-${SCENARIO}"
SESSION_B="fetcher-${SCENARIO}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' not on PATH" >&2; exit 1; }; }
need claude
need curl

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY not set. Try:" >&2
  echo "  export ANTHROPIC_API_KEY=\$(cat ~/.anthropic_key)" >&2
  exit 1
fi

echo "── smoke-multi-agent-peers ──"
echo "  leader      ${BASE_URL}"
echo "  scenario    ${SCENARIO}"
echo "  host A      ${HOST_A} -> session ${SESSION_A}"
echo "  host B      ${HOST_B} -> session ${SESSION_B}"
echo "  real nodes  ${REAL_NODES}"
echo

# ── preflight: leader must be reachable ──────────────────────────────────
http_code=$(curl -s --noproxy '*' -o /dev/null -w "%{http_code}" "${BASE_URL}/api/conversations" || true)
if [ "$http_code" != "200" ]; then
  echo "ERROR: leader Flask returned HTTP ${http_code} on /api/conversations — is it up?" >&2
  exit 2
fi

# ── drive agent A (first peer) ───────────────────────────────────────────
drive_agent() {
  local agent_host="$1"
  local session="$2"
  local prompt="$3"
  local url="${BASE_URL}/_scenario/${SCENARIO}/_session/${session}/v1/messages"

  if [ "$REAL_NODES" = "1" ]; then
    srun -N1 -n1 -w "$agent_host" --overlap \
      env ANTHROPIC_BASE_URL="${BASE_URL}/_scenario/${SCENARIO}/_session/${session}" \
      claude -p "$prompt" >/dev/null
  else
    ANTHROPIC_BASE_URL="${BASE_URL}/_scenario/${SCENARIO}/_session/${session}" \
      claude -p "$prompt" --header "X-Agent-Host: ${agent_host}" >/dev/null 2>&1 \
      || ANTHROPIC_BASE_URL="${BASE_URL}/_scenario/${SCENARIO}/_session/${session}" \
         claude -p "$prompt" >/dev/null
  fi
}

echo "[1/3] driving agent A (planner) on host ${HOST_A}…"
drive_agent "$HOST_A" "$SESSION_A" "What is 7 times 8? Answer in one number."
echo "      done"

echo "[2/3] driving agent B (fetcher) on host ${HOST_B}…"
drive_agent "$HOST_B" "$SESSION_B" "Name one planet with rings."
echo "      done"

# ── simulate a peer call A → B via the ingest endpoint ───────────────────
echo "[3/3] posting inter-agent start/done (planner → fetcher)…"
corr="smoke-$(date +%s%N)"

curl -sS --noproxy '*' -X POST \
  "${BASE_URL}/api/_inter-agent/ingest" \
  -H "Content-Type: application/json" \
  -d "{
    \"scenario_id\": \"${SCENARIO}\",
    \"phase\": \"start\",
    \"correlation_id\": \"${corr}\",
    \"from_host\": \"${HOST_A}\", \"from_session\": \"${SESSION_A}\",
    \"to_host\":   \"${HOST_B}\", \"to_session\":   \"${SESSION_B}\",
    \"kind\": \"mcp_call\",
    \"tool_name\": \"call_remote_agent\",
    \"payload\": \"forward question to fetcher\"
  }" >/dev/null

sleep 0.2

curl -sS --noproxy '*' -X POST \
  "${BASE_URL}/api/_inter-agent/ingest" \
  -H "Content-Type: application/json" \
  -d "{
    \"scenario_id\": \"${SCENARIO}\",
    \"phase\": \"done\",
    \"correlation_id\": \"${corr}\",
    \"from_host\": \"${HOST_A}\", \"from_session\": \"${SESSION_A}\",
    \"to_host\":   \"${HOST_B}\", \"to_session\":   \"${SESSION_B}\",
    \"status\": \"ok\",
    \"latency_ms\": 145.0
  }" >/dev/null

# ── verify ───────────────────────────────────────────────────────────────
echo
echo "── verifying ──"

graph_json=$(curl -sS --noproxy '*' "${BASE_URL}/api/scenarios/${SCENARIO}/graph")

agents_count=$(echo "$graph_json" | grep -c '"agent_id"' || true)
edges_count=$(echo "$graph_json"  | grep -c '"kind":"inter_agent_msg"' || true)

echo "  scenario graph:"
if command -v jq >/dev/null 2>&1; then
  echo "$graph_json" | jq '{agents: [.agents[].agent_id], edges: (.edges | length)}'
else
  echo "$graph_json"
fi

if [ "$agents_count" -lt 2 ]; then
  echo "FAIL: expected ≥2 agents in scenario ${SCENARIO}, got ${agents_count}" >&2
  exit 3
fi
if [ "$edges_count" -lt 1 ]; then
  echo "FAIL: expected ≥1 inter-agent edge, got ${edges_count}" >&2
  exit 4
fi

echo
echo "PASS: scenario ${SCENARIO} has ${agents_count} agents and ${edges_count} inter-agent edge(s)"
echo "Open http://127.0.0.1:${PORT}/call-graph?tab=scenarios&scenario=${SCENARIO} to inspect."
