#!/usr/bin/env bash
# Brings up dt_demo_server + Flask on the leader compute node.
# Idempotent-ish: kills any prior instances we own before starting.
set -u

LEADER_PORT="${LEADER_PORT:-5050}"
SCRATCH="/mnt/common/amonsorodriguez/clio-core/build/conda-output/bld/rattler-build_iowarp-core_1776376434/work/build"
WRP_CONF="/mnt/common/amonsorodriguez/clio-core/build/conda-output/bld/rattler-build_iowarp-core_1776376434/work/context-exploration-engine/agent-interceptor/demo/wrp_conf.yaml"
CV_DIR="$HOME/clio-core/context-visualizer"
DT_LOG=/tmp/clio-dt.log
FLASK_LOG=/tmp/clio-flask.log

echo "── stopping any prior instances ──"
pkill -u "$USER" -f dt_demo_server     2>/dev/null && sleep 1
pkill -u "$USER" -f "context_visualizer" 2>/dev/null && sleep 1

echo "── activating conda iowarp ──"
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate iowarp

export SCRATCH
export LD_LIBRARY_PATH="$SCRATCH/bin:$SCRATCH/lib:$CONDA_PREFIX/lib:${LD_LIBRARY_PATH:-}"
export CHI_SERVER_CONF="$WRP_CONF"

echo "── env ──"
echo "  SCRATCH=$SCRATCH"
echo "  CHI_SERVER_CONF=$CHI_SERVER_CONF"
echo "  LD_LIBRARY_PATH=$LD_LIBRARY_PATH"

if [ ! -x "$SCRATCH/bin/dt_demo_server" ]; then
  echo "FATAL: $SCRATCH/bin/dt_demo_server not executable"
  exit 1
fi
if [ ! -f "$WRP_CONF" ]; then
  echo "FATAL: $WRP_CONF not found"
  exit 1
fi

echo "── starting dt_demo_server (logs: $DT_LOG) ──"
: > "$DT_LOG"
nohup "$SCRATCH/bin/dt_demo_server" >>"$DT_LOG" 2>&1 &
DT_PID=$!
echo "  dt_demo_server PID=$DT_PID"

# Give chimaera + chimods time to compose (CTE, proxy, tracker, etc.)
sleep 6

if ! kill -0 "$DT_PID" 2>/dev/null; then
  echo "FATAL: dt_demo_server exited within 6s. Tail of $DT_LOG:"
  tail -30 "$DT_LOG"
  exit 2
fi

echo "── starting Flask context_visualizer on :$LEADER_PORT (logs: $FLASK_LOG) ──"
: > "$FLASK_LOG"
cd "$CV_DIR"
nohup python -m context_visualizer --host 0.0.0.0 --port "$LEADER_PORT" >>"$FLASK_LOG" 2>&1 &
FLASK_PID=$!
echo "  flask PID=$FLASK_PID"

# Poll Flask until /api/conversations responds 200 or timeout.
echo "── waiting for Flask to respond ──"
for i in $(seq 1 30); do
  code=$(curl -s --noproxy '*' --max-time 2 -o /dev/null -w "%{http_code}" \
         "http://127.0.0.1:$LEADER_PORT/api/conversations" 2>/dev/null || true)
  if [ "$code" = "200" ]; then
    echo "  OK after ${i}s — HTTP 200"
    echo "DT_PID=$DT_PID"
    echo "FLASK_PID=$FLASK_PID"
    exit 0
  fi
  sleep 1
done

echo "FATAL: Flask did not become healthy in 30s. Tail of $FLASK_LOG:"
tail -40 "$FLASK_LOG"
echo "--- dt_demo_server log tail ---"
tail -20 "$DT_LOG"
exit 3
