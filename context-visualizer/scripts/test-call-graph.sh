#!/usr/bin/env bash
# Drive the agent-interception multi_Agent_graph scripts against our Flask
# dispatcher at :5000 so the /call-graph view has realistic traffic to render.
#
# Env:
#   INTERCEPTOR_URL   Override Flask base URL (default http://127.0.0.1:5000)
#   ANTHROPIC_API_KEY Required. Falls back to ~/.anthropic_key.
#   SCRIPTS="a,b"     Run only these (without .py). Default is a sensible set.
#   SKIP="a,b"        Skip these (takes precedence over SCRIPTS).
#
# Expected state before running:
#   - dt_demo_server running on comp-11 (Terminal A in setup-guide.md)
#   - Flask running on :5000 in the same iowarp env (Terminal B)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EXT_DIR="$REPO_DIR/external/agent-interception"
VENV_DIR="$EXT_DIR/.venv"
FLASK_URL="${INTERCEPTOR_URL:-http://127.0.0.1:5000}"

hr() { printf '%s\n' "============================================================"; }

# ---- Preflight ----------------------------------------------------------

if ! command -v python >/dev/null 2>&1; then
    echo "ERROR: 'python' not on PATH. Activate the iowarp env first:" >&2
    echo "  conda activate iowarp" >&2
    exit 1
fi

PY_VER="$(python -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
PY_MAJOR="${PY_VER%.*}"
PY_MINOR="${PY_VER#*.}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "ERROR: need Python >=3.11, got $PY_VER. Activate iowarp env." >&2
    exit 1
fi

if ! curl -sf --noproxy '*' "$FLASK_URL/_interceptor/health" >/dev/null; then
    echo "ERROR: Flask not reachable at $FLASK_URL" >&2
    echo "Start it in another terminal:" >&2
    echo "  conda activate iowarp" >&2
    echo "  export CHI_SERVER_CONF=/mnt/common/amonsorodriguez/clio-core/context-exploration-engine/agent-interceptor/demo/wrp_conf.yaml" >&2
    echo "  python -m context_visualizer --host 0.0.0.0 --port 5000" >&2
    exit 1
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    if [ -f "$HOME/.anthropic_key" ]; then
        ANTHROPIC_API_KEY="$(cat "$HOME/.anthropic_key")"
        export ANTHROPIC_API_KEY
    else
        echo "ERROR: ANTHROPIC_API_KEY not set and ~/.anthropic_key missing" >&2
        exit 1
    fi
fi

# Let local Flask bypass the corporate Squid proxy that iowarp users often
# have in their shell env.
export no_proxy="localhost,127.0.0.1,ares-comp-11,ares,${no_proxy:-}"
export NO_PROXY="$no_proxy"

# Ensure claude CLI is findable for the scripts that spawn it directly.
if ! command -v claude >/dev/null 2>&1; then
    if [ -d "$HOME/.npm-global/bin" ]; then
        export PATH="$HOME/.npm-global/bin:$PATH"
    fi
fi

# ---- Clone + venv -------------------------------------------------------

if [ ! -d "$EXT_DIR/.git" ]; then
    echo "Cloning JaimeCernuda/agent-interception (branch: multi_Agent_graph)..."
    git clone --depth 1 --branch multi_Agent_graph \
        https://github.com/JaimeCernuda/agent-interception "$EXT_DIR"
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating venv at $VENV_DIR..."
    python -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
    "$VENV_DIR/bin/pip" install "claude-agent-sdk==0.1.39" "anthropic>=0.84.0" "httpx>=0.28"
fi

# ---- Runner -------------------------------------------------------------

export INTERCEPTOR_URL="$FLASK_URL"

# Order matters: cheap → heavy. verify_logs.py excluded (needs endpoints we
# don't expose).
DEFAULT_SCRIPTS="code_review,multi_turn_refactor,generate_report,parallel_analysis,demo_multi_agent,multi_agent_audit,concurrent_sessions_test,design_discussion"
IFS=',' read -r -a ALL_SCRIPTS <<< "${SCRIPTS:-$DEFAULT_SCRIPTS}"

is_skipped() {
    local n="$1"
    [ -z "${SKIP:-}" ] && return 1
    IFS=',' read -r -a skip_arr <<< "$SKIP"
    for s in "${skip_arr[@]}"; do
        [ "$s" = "$n" ] && return 0
    done
    return 1
}

count_conversations() {
    curl -sf --noproxy '*' "$FLASK_URL/api/conversations" 2>/dev/null \
        | python -c 'import json,sys
try:
    d = json.load(sys.stdin)
    if isinstance(d, list): print(len(d))
    elif isinstance(d, dict) and "conversations" in d: print(len(d["conversations"]))
    else: print(0)
except Exception:
    print("?")' 2>/dev/null || echo "?"
}

cd "$EXT_DIR"

hr
echo "  Call-Graph test suite"
echo "  Flask:  $FLASK_URL"
echo "  Venv:   $VENV_DIR"
echo "  Python: $($VENV_DIR/bin/python -V)"
echo "  Plan:   ${ALL_SCRIPTS[*]}"
[ -n "${SKIP:-}" ] && echo "  Skip:   $SKIP"
hr

initial=$(count_conversations)
echo "Conversations before run: $initial"
echo

FAIL_COUNT=0
PASS_COUNT=0
SKIP_COUNT=0

for name in "${ALL_SCRIPTS[@]}"; do
    name="$(echo "$name" | xargs)"  # trim
    [ -z "$name" ] && continue
    if is_skipped "$name"; then
        echo "-- SKIP $name (via SKIP=)"
        SKIP_COUNT=$((SKIP_COUNT+1))
        continue
    fi
    script_path="scripts/${name}.py"
    if [ ! -f "$script_path" ]; then
        echo "-- MISSING $script_path, skipping"
        SKIP_COUNT=$((SKIP_COUNT+1))
        continue
    fi

    hr
    echo "  Running: $name"
    hr
    before=$(count_conversations)
    if "$VENV_DIR/bin/python" "$script_path"; then
        PASS_COUNT=$((PASS_COUNT+1))
        echo ">> OK: $name"
    else
        FAIL_COUNT=$((FAIL_COUNT+1))
        echo ">> FAIL: $name exited non-zero (traffic may still have landed)"
    fi
    after=$(count_conversations)
    echo "   conversations: before=$before after=$after"
    echo
done

hr
echo "  Summary"
echo "  pass:    $PASS_COUNT"
echo "  fail:    $FAIL_COUNT"
echo "  skipped: $SKIP_COUNT"
echo "  conversations now: $(count_conversations) (was $initial)"
echo
echo "  Open $FLASK_URL/call-graph in your browser."
echo "  Try: View = Aggregate + Scope = Full workflow for multi-agent runs."
hr

# Exit non-zero if any script failed, so CI can pick up on it.
[ "$FAIL_COUNT" -eq 0 ] || exit 2
