# Local setup: running the full workspace-observability stack

End-to-end what it takes to get `claude` → interceptor → Chimaera →
visualizer → browser all talking on the ares cluster. Assumes you're
starting from a fresh laptop terminal.

## Components and where each runs

| Component | Host | Port | Process |
|---|---|---|---|
| `dt_demo_server` (tracker + proxy chimod + Chimaera runtime) | `ares-comp-11` | 9514 (Chimaera RPC) | foreground |
| `context_visualizer` (Flask dashboard + workspace SPA **and** LLM-dispatch bridge at `/_session/…`) | `ares-comp-11` | 5000 | foreground |
| `claude` CLI (driver for test traffic) | `ares-comp-11` | n/a | one-shot per query |
| SSH tunnel (laptop → comp-11:5000) | laptop | 5000 | foreground |
| Browser at `http://127.0.0.1:5000/workspace` | laptop | — | — |

Four terminals total: one tunnel + three SSH sessions on comp-11.

## One-time prerequisites

Do these once per account on `ares-comp-11`. Skip if already done.

1. **Conda + iowarp env.** You ran `./install.sh` from
   `~/clio-core`. Confirm with `ls ~/miniconda3/envs/iowarp/bin/chimaera`.
2. **SPA bundle built.** Confirm
   `context-visualizer/context_visualizer/static/workspace/index.html`
   exists. If not:
   ```bash
   cd ~/clio-core/context-visualizer
   make workspace
   ```
3. **Python visualizer deps.** Installed once via `pip install flask
   pyyaml msgpack` inside the `iowarp` env. If you get an `ImportError`
   starting Flask, rerun.
4. **`claude` CLI.** Installed via user-local npm:
   ```bash
   mkdir -p ~/.npm-global
   npm config set prefix ~/.npm-global
   export PATH=~/.npm-global/bin:$PATH   # add to ~/.bashrc to persist
   npm install -g @anthropic-ai/claude-code
   ```
5. **Anthropic API key stored securely.** Put it in a file with 600
   perms so you never paste it into chat:
   ```bash
   umask 077
   echo "sk-ant-..." > ~/.anthropic_key
   chmod 600 ~/.anthropic_key
   ```

## Each-session startup (do this every time you come back)

### Step 1 — claim a compute allocation and SSH in

**On your laptop:**
```bash
ssh amonsorodriguez@ares
salloc -N 1 --time=48:00:00      # or reuse an existing allocation
ssh ares-comp-11
```

### Step 2 — start `dt_demo_server` (Terminal A on comp-11)

Paste as one block:

```bash
conda activate iowarp
export SCRATCH=/mnt/common/amonsorodriguez/clio-core/build/conda-output/bld/rattler-build_iowarp-core_1776376434/work/build
export LD_LIBRARY_PATH="$SCRATCH/bin:$SCRATCH/lib:$CONDA_PREFIX/lib"
export CHI_SERVER_CONF=/mnt/common/amonsorodriguez/clio-core/context-exploration-engine/agent-interceptor/demo/wrp_conf.yaml
"$SCRATCH/bin/dt_demo_server"
```

Wait for startup logs to settle. Leave this terminal blocked on the
server — closing it kills the runtime.

> **Why the `SCRATCH` path?** `install.sh` builds via rattler-build
> (conda packaging), which installs Chimaera into the iowarp env but
> leaves `dt_demo_server` in the rattler build scratch directory.
> We point `LD_LIBRARY_PATH` at that scratch dir to use the interceptor
> binaries directly. The patched
> `libdt_provenance_dt_intercept_anthropic_runtime.so` is there too —
> required for egress through Squid.

### Step 3 — start the visualizer (Terminal B on comp-11)

New SSH session to comp-11. Paste:

```bash
conda activate iowarp
# Critical: Flask must read the SAME runtime config as dt_demo_server,
# otherwise its Chimaera client defaults to port 9413 while the server
# binds 9513 (read from wrp_conf.yaml), and every /_session/ POST
# returns 502 "Chimaera dispatch failed".
export CHI_SERVER_CONF=/mnt/common/amonsorodriguez/clio-core/context-exploration-engine/agent-interceptor/demo/wrp_conf.yaml
# Also: Flask must run inside the iowarp env, not the base Python.
# chimaera_runtime_ext is built for Python 3.14; other Pythons can't
# load the .so and /_session/ POSTs silently return 502 while /api
# endpoints return empty lists.
python --version                  # expect 3.14.x
python -c "import chimaera_runtime_ext; print('ok')"
cd ~/clio-core/context-visualizer
python -m context_visualizer --host 0.0.0.0 --port 5000
```

Expect:
```
 * Running on http://127.0.0.1:5000
```

Connection errors to the Chimaera runtime are fine if Terminal A
hasn't fully come up yet — dashboard panels will just show a banner.

### Step 4 — open the browser tunnel (Terminal C on laptop)

**On your laptop:**
```bash
ssh -L 5000:ares-comp-11:5000 amonsorodriguez@ares
```

Leave the session idle, just keep it open. Then visit
<http://127.0.0.1:5000/workspace> in your browser.

### Step 5 — drive test traffic (Terminal D on comp-11)

New SSH session to comp-11. Paste:

```bash
export no_proxy="localhost,127.0.0.1,ares-comp-11,ares"
export NO_PROXY="$no_proxy"
export ANTHROPIC_API_KEY=$(cat ~/.anthropic_key)
ANTHROPIC_BASE_URL="http://ares-comp-11:5000/_session/my-convo" \
  claude -p "What is 2+2?"
```

You should get a 4-ish response. Refresh `/workspace` — a conversation
row labeled `my-convo` should appear on the left. Click it.

> **Why both `no_proxy` and `NO_PROXY`?** Node (which `claude` runs on)
> reads the uppercase form; libcurl and many Python libs read the
> lowercase. Setting both is the safe default. Without this, `claude`
> would try to reach `http://ares-comp-11:5000/...` through Squid and
> get a "URL could not be retrieved" error.

### Step 6 — multi-agent (optional, shows the view's real point)

In Terminal D:

```bash
ANTHROPIC_BASE_URL="http://ares-comp-11:5000/_session/trip-planner"   claude -p "Plan a 3-day Tokyo trip."
ANTHROPIC_BASE_URL="http://ares-comp-11:5000/_session/trip-planner.1" claude -p "5 things in Shibuya."
ANTHROPIC_BASE_URL="http://ares-comp-11:5000/_session/trip-planner.2" claude -p "3 ramen places."
```

All three share base id `trip-planner`, so they collapse into one
conversation row in the workspace. Clicking it shows one orchestrator
node (`trip-planner`) + two subagent nodes on the agent graph, with
interactions interleaved on the timeline.

## Multi-agent + tool-use smoke tests

Once the four-terminal setup is alive, drive realistic traffic with
either a ready-made script or the existing SDK-based tests from the
interceptor repo.

### Option A — `smoke-multiagent.sh` (no Python setup needed)

Lives at `context-visualizer/scripts/smoke-multiagent.sh`. Uses the
`claude` CLI you already installed. Covers four levels: basic / Bash
tool / Read+Bash chained / orchestrator + 2 subagents (hierarchical
session ids so the workspace collapses them into one conversation row).

```bash
# In any free SSH session on ares-comp-11:
export ANTHROPIC_API_KEY=$(cat ~/.anthropic_key)
bash ~/clio-core/context-visualizer/scripts/smoke-multiagent.sh
```

Set `DTP_SKIP=basic,multiturn` etc. to skip specific tests, or
`DTP_PREFIX=my-run` to override the session-id prefix. At the end the
script prints which conversations ended up in `/api/conversations` so
you can find them in the browser.

### Option B — the original SDK-based scripts

They still work if you set up a venv with `claude-agent-sdk` and pass
the new port on the CLI.

```bash
cd ~/clio-core/context-exploration-engine/agent-interceptor/deploy
python3 -m venv .venv
.venv/bin/pip install claude-agent-sdk

# Three agents sharing a parent id so the workspace shows one row with
# a 3-node graph. --proxy-port is 5000 (not 9090 like the README says —
# that was the old standalone proxy era).
.venv/bin/python run_agents.py \
    --proxy-host ares-comp-11 \
    --proxy-port 5000 \
    --sessions trip-planner trip-planner.1 trip-planner.2 \
    --prompts "Plan a trip to Kyoto." "5 temples to visit." "3 ryokans."

# Full 5-case integration suite (single / multi / resume / isolation /
# tracker state). Reports PASS/FAIL per case.
.venv/bin/python integration_test.py \
    --build-dir ~/clio-core/build \
    --proxy-port 5000
```

If `pip install` fails with SSL/proxy errors inside the venv, the
cluster's `https_proxy` is already exported in your shell so pip should
just work — check `pip config list` doesn't override it.



If something looks wrong, run these in Terminal D (or any shell on
comp-11) and paste the output:

```bash
# Is dt_demo_server listening on :9090?
curl -s --noproxy '*' -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:9090/

# Is Flask up on :5000?
curl -s --noproxy '*' -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:5000/

# Does Flask see any sessions yet?
curl -s --noproxy '*' http://127.0.0.1:5000/api/conversations | python3 -m json.tool | head -40

# Is the patched anthropic .so actually loaded?
pgrep -u "$USER" -af dt_demo_server
# note the pid, then:
PID=<pid>
grep libdt_provenance_dt_intercept_anthropic_runtime /proc/$PID/maps | head -1
# should point at $SCRATCH/bin/
```

## Shutdown (so you don't leak processes)

In Terminal A, `Ctrl+C` `dt_demo_server`. In Terminal B, `Ctrl+C`
Flask. Close Terminal C and D normally. If `Ctrl+C` corrupts terminal
state (cursor becomes a block, paste stops working):

```bash
stty sane
# or if that doesn't help:
reset
```

`salloc` allocation stays alive until you `exit` the outer ares shell
or its `--time` elapses.

## Common errors

| Symptom | Cause | Fix |
|---|---|---|
| `claude: command not found` | npm global bin not on PATH | `export PATH=~/.npm-global/bin:$PATH` (add to `~/.bashrc`) |
| "The requested URL could not be retrieved" in `claude` output | Node sent the request through Squid instead of to the local proxy | Set `no_proxy`/`NO_PROXY` to include `ares-comp-11,127.0.0.1` |
| `claude` works but conversations don't appear in `/workspace` | Flask not pointed at the same Chimaera runtime | Confirm `CHI_SERVER_CONF` matches between `dt_demo_server` and Flask, and both ran inside the same `iowarp` conda env |
| `make workspace` produces new hashed asset names but browser shows old UI | Browser cache | Hard refresh: `Cmd+Shift+R` |
| `dt_demo_server` logs `bad file: <path>wrp_conf.yaml<something>` | `CHI_SERVER_CONF` got concatenated with another command (paste error) | Re-export cleanly: `export CHI_SERVER_CONF=/absolute/path/wrp_conf.yaml`, then verify with `echo "$CHI_SERVER_CONF"` |
| Tunnel succeeds but browser says "Connection refused" | Flask isn't running (or bound to the wrong iface) | Terminal B must be active and show `Running on http://127.0.0.1:5000` |
| `ssh -J ... ares-comp-11` asks passphrase twice then "Permission denied" | Compute node doesn't accept direct SSH from off-cluster | Use the two-hop form instead: `ssh ares` → `ssh ares-comp-11` |

## Security notes

- Never paste your Anthropic API key into chat, tickets, or git. Store
  it in `~/.anthropic_key` (mode 600) and `export ANTHROPIC_API_KEY=$(cat ~/.anthropic_key)`.
- If you ever do leak a key, rotate it at
  <https://console.anthropic.com/settings/keys> immediately and clear
  your shell history: `history -c && unset ANTHROPIC_API_KEY`.
- `http_proxy` already carries `squid_user:squid_user` creds in the
  shell env — don't share screenshots of `env` output from the
  compute node outside your team.
