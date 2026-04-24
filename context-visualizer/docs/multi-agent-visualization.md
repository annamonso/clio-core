# Multi-Agent Visualization — Architecture, Detection, and Demos

This document explains how `context-visualizer` represents multi-agent workloads
across multiple HPC nodes: the conceptual model, the cross-node detection
mechanism, the data schema, and how to author a scenario end-to-end.

> Sibling docs: [`setup-guide.md`](setup-guide.md) (how to run the stack on
> ares-comp-N), [`workspace.md`](workspace.md) (the React workspace tab),

---

## 1. What this is

Modern AI workloads are no longer a single agent talking to a single LLM. They
are graphs: orchestrators that delegate to sub-agents; peer agents that call
each other across machines via MCP; tool-use chains that fan out and back. Each
step issues opaque HTTP traffic to the LLM, and operators get no visibility
into:

- Which agent is talking to which other agent right now
- Which physical node each agent is running on
- How the cost / token budget is split across the graph
- Whether a cross-node call succeeded, errored, or was retried

The **multi-agent visualizer** answers all four. It captures every LLM
interaction at the network layer (transparent HTTPS proxy) and every
inter-agent message at the call-site (an explicit ingest endpoint), then renders
two complementary views:

| View | Question it answers | Where in UI |
|---|---|---|
| **Workspace** | "What did *this* agent do, turn by turn?" | Tab `Workspace` |
| **Scenarios** | "How are these agents connected across the cluster?" | Tab `Scenarios` |

Both are populated from the same back-end data, joined by three orthogonal
identifiers: `host`, `scenario_id`, `session_id`.

---

## 2. Conceptual model

### 2.1 The five entities

```
┌─────────────────────────────────────────────────────────────────────┐
│ HOST          a physical compute node ("ares-comp-11")              │
│ ─────         identifies *where* an agent is physically running     │
│                                                                     │
│ SCENARIO      a named, user-chosen experiment ("demo-6")            │
│ ────────      identifies *which experiment* a set of calls belongs  │
│               to. Independent of host. One scenario can span many   │
│               hosts; one host can run many scenarios.               │
│                                                                     │
│ AGENT         a peer-level actor in a scenario ("planner")          │
│ ─────         identified by its base session id; the unit shown as  │
│               a node in the Scenarios tab graph.                    │
│                                                                     │
│ SESSION       one continuous LLM conversation ("planner")           │
│ ───────       1:1 with an Agent's "main thread". Numbered children  │
│               (.2, .3, .4) are sub-sessions = subagents/Task tool.  │
│                                                                     │
│ INTERACTION   a single LLM HTTP request/response pair               │
│ ───────────   the smallest unit; carries tokens, cost, content,     │
│               status code, timestamps, and back-references to       │
│               host/scenario/session.                                │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 The hierarchy in plain English

> **Cluster** has many **Hosts**.
> Each **Host** can run many **Sessions** at the same time.
> A **Scenario** groups Sessions across Hosts into one experiment.
> Within a Scenario, each base session id is one **Agent**.
> An Agent has a main Session and zero-or-more sub-sessions (its subagents).
> Each Session has many **Interactions** (LLM calls).
> Cross-Agent calls become **Edges** in the Scenario graph.

### 2.3 Why we picked this carve-up

- **Scenario** is the user-controlled tag. It maps 1:1 to whatever experiment
  the operator is running. Operators rename scenarios; they never rename hosts.
- **Host** is physical. The interceptor records it from the URL prefix or the
  `X-Agent-Host` header, never from request IP (which would be the Flask host).
- **Agent** is the *peer-level* actor — the thing you would name on a slide
  ("the planner sent the question to the executor"). It is a roll-up of one
  base session id plus all its hierarchical children.
- **Session** is the LLM-protocol primitive — what each `claude -p` invocation
  carries forward. Sub-session ids (`planner.2`, `planner.2.3`) are emitted by
  the agent SDK when it spawns subagents (Task tool, MCP relay).
- **Interaction** is the operational primitive — what the proxy sees on the
  wire. Everything ultimately boils down to a list of these.

---

## 3. Architecture

### 3.1 End-to-end data flow

```
                            ┌─────────────────┐
   claude CLI on            │ ANTHROPIC_BASE_URL = http://flask:5050/_host/H/_scenario/S/_session/X
   ares-comp-11             │ (no API client lib changes — pure URL routing)
   (or comp-16, ...)        └────────┬────────┘
                                     │ HTTPS POST /v1/messages
                                     ▼
                            ┌─────────────────┐
                            │ Flask           │  context_visualizer/api/llm_dispatch.py
                            │ /_host/.../     │    parses URL prefix → (host, scenario, session)
                            │ /_scenario/.../ │    detects provider (anthropic/openai/ollama)
                            │ /_session/...   │    forwards into Chimaera RPC
                            └────────┬────────┘
                                     │ Chimaera Monitor query
                                     ▼
   on the same node:        ┌─────────────────┐
                            │ proxy ChiMod    │  proxy_runtime.cc::BuildInteractionRecord
   dt_demo_server           │ (per provider)  │    fills InteractionRecord{
   process; loads all       │                 │      session, scenario_id, host,
   chimods into one         │ MITM:           │      provider, status, timestamp,
   Chimaera runtime.        │ - decode SSE    │      delta_input/output_tokens,
                            │ - re-encode     │      delta_cost_usd, body, ...
                            │ - record body   │    }
                            └────────┬────────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │ tracker ChiMod  │  tracker_runtime.cc
                            │                 │    aggregates by (scenario_id, session)
                            │ CTE PutBlob     │    persists per-tag blob
                            └────────┬────────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │ /api/sessions   │  Flask reads CTE blobs
                            │ /api/conversations
                            │ /api/scenarios  │
                            │ /api/scenarios/<sid>/graph
                            └────────┬────────┘
                                     │ JSON
                                     ▼
                            ┌─────────────────┐
                            │ React SPA       │  /call-graph
                            │ Workspace tab   │
                            │ Scenarios tab   │
                            │ Interactions    │
                            └─────────────────┘
```

### 3.2 Two parallel ingest paths

There are **two separate paths** by which information enters the system. They
record different things and they have different durability properties — get
this right or you will be confused later.

**Path A: LLM interactions (transparent capture).**
- Triggered by every HTTP request the agent makes to the LLM.
- Goes through the proxy ChiMod and lands in the tracker's CTE blob storage.
- Records what *each agent* did internally: tool calls, sub-session spawns,
  tokens, cost, response content.
- Storage is **in-memory** to dt_demo_server. **A restart wipes it.**

**Path B: Inter-agent edges (explicit capture).**
- Triggered by an MCP relay (or any other wrapper) calling
  `/api/_inter-agent/ingest` with a `{phase: "start" | "done", ...}` JSON body.
- Goes through `context_visualizer/api/inter_agent.py` into the Flask-side
  `InterAgentStore`.
- Records the *fact that agent A called agent B* (with from/to host, latency,
  status, payload preview).
- Storage is **Flask-side**. Survives `dt_demo_server` restart.

The Scenarios tab graph **joins both paths**:
- `agents[]` come from Path A (which agents have done LLM work)
- `edges[]` come from Path B (which agents called which)
- An agent that appears in Path B but not Path A still shows up as a node, but
  with `interaction_count: 0` and `host: ""`.

This is by design — it lets you draw the topology of an experiment before any
LLM call happens, and lets you record edges even when the called agent is
implemented in a non-LLM way (e.g. a python service).

---

## 4. How we detect interactions between nodes

There are **two distinct mechanisms** for cross-node visibility, and both must
be present for the Scenarios graph to make sense:

### 4.1 Per-call host stamping (URL prefix)

The claude CLI cannot set custom HTTP headers per request, so we route the
host identification through the URL itself. The base URL the agent uses
encodes `host`, `scenario`, and `session` as path prefixes:

```
http://<flask-host>:5050/_host/<HOSTNAME>/_scenario/<SID>/_session/<SESSION>/v1/messages
                       │       │                 │             │
                       │       │                 │             └── opaque to flask;
                       │       │                 │                  forwarded to provider
                       │       │                 │
                       │       │                 └── stamps InteractionRecord.session
                       │       │
                       │       └── stamps InteractionRecord.scenario_id
                       │
                       └── stamps InteractionRecord.host
```

Routing rules in `context_visualizer/api/llm_dispatch.py:430-455`:

| URL pattern | What gets stamped |
|---|---|
| `/_host/<H>/_scenario/<S>/_session/<X>/...` | host + scenario + session |
| `/_host/<H>/_session/<X>/...` | host + session |
| `/_scenario/<S>/_session/<X>/...` | scenario + session |
| `/_session/<X>/...` | session only (legacy) |

Fallback: if no `/_host/<H>/` prefix is present, `llm_dispatch.py:493` checks
the `X-Agent-Host` HTTP header. Useful for the MCP relay; not useful for
claude CLI.

> ⚠ **First-call attribution sticks.** `scenario_adapter.py:67` derives each
> agent's host by *most-frequent-host vote* across all its interactions. If the
> first batch of LLM calls reaches Flask without `/_host/<h>/`, Flask
> attributes them to its own hostname (the node Flask runs on), and a later
> "corrective" call with the proper prefix will not flip the vote. **Always
> include `/_host/<HOSTNAME>/` from interaction #1.** A real bug seen on
> 2026-04-23 with `demo-3`: 21 wrongly-tagged interactions vs 1 corrective →
> agent stayed pinned to wrong host. Had to start over with a fresh
> scenario id.

### 4.2 Edge events (explicit ingest)

Inter-agent calls are recorded by POSTing **two events** per call (start and
done), keyed by a `correlation_id` that the caller chooses (any unique string
works; we use `<scenario>-<nanoseconds>`):

```
POST http://<flask-host>:5050/api/_inter-agent/ingest
Content-Type: application/json

# Phase 1 — at call initiation
{
  "scenario_id":     "demo-6",                 # required
  "phase":           "start",                  # required
  "correlation_id":  "demo6-1776995490867975268",  # optional (auto-generated)
  "from_host":       "ares-comp-11",           # required
  "from_session":    "planner",                # required
  "to_host":         "ares-comp-16",           # required
  "to_session":      "executor",               # required
  "kind":            "mcp_call",               # optional, default "mcp_call"
  "tool_name":       "delegate_to_executor",   # optional
  "payload":         "need executor to gather memory and uptime info"  # optional; hashed + truncated to 512 chars
}

# Phase 2 — at call completion (same correlation_id)
{
  "scenario_id":     "demo-6",
  "phase":           "done",
  "correlation_id":  "demo6-1776995490867975268",
  "from_host":       "ares-comp-11",
  "from_session":    "planner",
  "to_host":         "ares-comp-16",
  "to_session":      "executor",
  "status":          "ok",                     # or "error:<msg>"
  "latency_ms":      268.0
}
```

The two events are stitched into one edge by `correlation_id`. See
`context_visualizer/api/inter_agent.py:52-134` for the ingest schema and
`scenario_adapter.py:124-144` for the stitched edge format.

**Who calls this endpoint?**
- The **MCP relay server** at `context-exploration-engine/agent-interceptor/
  inter_agent_relay/` automatically posts start/done around every MCP call it
  proxies — this is the production path.
- For demos and tests, you can POST it manually with `curl`. We do this in
  `scripts/smoke-multi-agent-peers.sh` and in the demo-5/demo-6 workflows
  below.

**Why two paths and not one?**
The HTTP-MITM proxy can see *that* an agent issued an LLM call, but it cannot
see *that* one agent invoked another agent — that interaction happens off-band
(via MCP, REST, gRPC, whatever). The relay knows; the proxy doesn't. So we
record edges separately.

---

## 5. Data schema

### 5.1 `InteractionRecord` (C++, written by proxy)

Defined in `context-exploration-engine/agent-interceptor/interception/anthropic/
include/.../proxy_types.h` (similar for openai/ollama). The fields the
visualizer cares about:

```
struct InteractionRecord {
  std::string  session;            // session id (e.g. "planner.2")
  std::string  scenario_id;        // from /_scenario/<S>/ URL prefix
  std::string  host;               // from /_host/<H>/ URL prefix or X-Agent-Host
  std::string  provider;           // "anthropic" | "openai" | "ollama"
  int          status;             // HTTP status from upstream (200, 401, 429, ...)
  std::string  timestamp;          // ISO-8601 UTC (added by commit fabc2a79)
  uint64_t     delta_input_tokens;
  uint64_t     delta_output_tokens;
  double       delta_cost_usd;
  std::string  request_body;       // full payload
  std::string  response_body;      // full payload
  // ... + correlation, headers, etc.
};
```

### 5.2 `InterAgentMessage` (Python, written by ingest endpoint)

Defined in `context_visualizer/inter_agent/store.py`. After stitching:

```python
{
  "correlation_id":   str,         # the join key
  "scenario_id":      str,
  "from_host":        str,
  "from_session":     str,
  "to_host":          str,
  "to_session":       str,
  "kind":             str,         # "mcp_call" by default
  "tool_name":        str,
  "payload_preview":  str,         # truncated to 512 chars
  "payload_digest":   str,         # "sha256:<hex>"
  "status":           str,         # "ok" | "error:<msg>"
  "latency_ms":       float,
  "ts_start":         str,         # ISO-8601 UTC
  "ts_done":          str,
}
```

### 5.3 `ScenarioGraph` (the API response)

What `/api/scenarios/<sid>/graph` returns. Built by
`scenario_adapter.build_scenario_graph`:

```jsonc
{
  "scenario_id": "demo-6",
  "agents": [                    // peer-level nodes (one per base session id)
    {
      "agent_id":          "planner",
      "session_id":        "planner",         // base session id
      "agent_role":        "peer",            // always "peer" at scenario level
      "host":              "ares-comp-11",    // most-frequent-host vote
      "interaction_count": 39,
      "total_tokens":      2033,
      "total_cost_usd":    0.345,
      "sub_sessions":      ["planner", "planner.2", "planner.3", ..., "planner.10"]
    },
    { "agent_id": "executor", "host": "ares-comp-16", ... }
  ],
  "edges": [
    {
      "kind":            "inter_agent_msg",
      "event_id":        "demo6-1776995490867975268",     // = correlation_id
      "from_session_id": "planner",         // base id
      "from_sub_session_id": "planner",     // exact id (may include .2/.3 suffix)
      "to_session_id":   "executor",
      "to_sub_session_id": "executor",
      "from_host":       "ares-comp-11",
      "to_host":         "ares-comp-16",
      "tool_name":       "delegate_to_executor",
      "status":          "ok",
      "latency_ms":      268.0,
      "ts_start":        "2026-04-24T01:51:30.889179Z",
      "ts_done":         "2026-04-24T01:51:31.920091Z",
      "payload_preview": "need executor to gather memory and uptime info"
    }
  ]
}
```

---

## 6. End-to-end worked example: `demo-5` and `demo-6`

Both run a 2-host setup with one peer agent per host. `demo-5` exercises tools
and Task subagents at the parent level; `demo-6` extends it so the Task
subagents themselves use tools — producing several layers of depth under each
peer in the Workspace tab.

### 6.1 Prerequisites

A 2-node SLURM allocation with `dt_demo_server` + Flask up on the leader. See
[`setup-guide.md`](setup-guide.md) for the full bring-up; the abbreviated
version:

```bash
# Login node
salloc -N 1 --time=4:00:00 --no-shell                         # leader (e.g. comp-11)
salloc -N 1 --time=4:00:00 --no-shell --exclude=ares-comp-11  # peer   (e.g. comp-16)
squeue -u $USER                                               # confirm both jobs R

# Launch services on the leader (use ssh, NOT srun bash -c — see Pitfalls §8)
ssh ares-comp-11 'bash -c "
  source $HOME/miniconda3/etc/profile.d/conda.sh
  conda activate iowarp
  export SCRATCH=/mnt/.../rattler-build_iowarp-core_1776376434/work/build
  export LD_LIBRARY_PATH=\"$SCRATCH/bin:$SCRATCH/lib:$CONDA_PREFIX/lib\"
  export CHI_SERVER_CONF=/mnt/.../wrp_conf.yaml
  nohup \"$SCRATCH/bin/dt_demo_server\" > /tmp/clio-dt.log 2>&1 &
  cd \$HOME/clio-core/context-visualizer
  nohup python -m context_visualizer --host 0.0.0.0 --port 5050 > /tmp/clio-flask.log 2>&1 &
"'
```

Then on your laptop:
```bash
ssh -L 18051:ares-comp-11:5050 amonsorodriguez@ares
# browser: http://127.0.0.1:18051/call-graph
```

### 6.2 Demo-5 — 2-host scenario with subagents

A **planner on comp-11** delegates to an **executor on comp-16**. Each agent
exercises Bash, Read, and the Task tool (which spawns a subagent).

```bash
ANTHROPIC_API_KEY=$(cat ~/.anthropic_key)

# Step 1: planner on comp-11 — exercises Bash, Read, Task subagent
srun -N1 -n1 -w ares-comp-11 --overlap --jobid=$LEADER_JOB \
  env PATH=/home/$USER/.local/bin:/usr/bin:/bin \
      ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
      ANTHROPIC_BASE_URL=http://ares-comp-11:5050/_host/ares-comp-11/_scenario/demo-5/_session/planner \
      no_proxy=localhost,127.0.0.1,ares-comp-11,ares-comp-16,ares \
      NO_PROXY=$no_proxy \
  claude --permission-mode bypassPermissions --max-turns 8 \
  -p "Planner agent. Step1 Bash hostname and pwd. \
      Step2 Read /etc/os-release. \
      Step3 Task subagent_type=general-purpose to delegate: \
            'name 2 popular CMake build flags'. \
      Step4 1-sentence summary."

# Step 2: executor on comp-16 — same shape, different host
srun -N1 -n1 -w ares-comp-16 --overlap --jobid=$PEER_JOB \
  env PATH=/home/$USER/.local/bin:/usr/bin:/bin \
      ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
      ANTHROPIC_BASE_URL=http://ares-comp-11:5050/_host/ares-comp-16/_scenario/demo-5/_session/executor \
      no_proxy=$no_proxy NO_PROXY=$no_proxy \
  claude --permission-mode bypassPermissions --max-turns 8 \
  -p "Executor agent. Step1 Bash hostname and uptime. \
      Step2 Bash 'ls /tmp | head -5'. \
      Step3 Task subagent_type=general-purpose: \
            'name 2 advantages of SLURM on HPC'. \
      Step4 1-sentence summary."

# Step 3: post the inter-agent edge linking them
ssh ares-comp-11 'bash -c "
  corr=demo5-\$(date +%s%N)
  curl -sS -X POST http://127.0.0.1:5050/api/_inter-agent/ingest \
       -H Content-Type:application/json \
       -d \"{\\\"scenario_id\\\":\\\"demo-5\\\",\\\"phase\\\":\\\"start\\\",
             \\\"correlation_id\\\":\\\"\$corr\\\",
             \\\"from_host\\\":\\\"ares-comp-11\\\",\\\"from_session\\\":\\\"planner\\\",
             \\\"to_host\\\":\\\"ares-comp-16\\\",\\\"to_session\\\":\\\"executor\\\",
             \\\"kind\\\":\\\"mcp_call\\\",\\\"tool_name\\\":\\\"delegate_to_executor\\\",
             \\\"payload\\\":\\\"need executor to gather system info\\\"}\"
  sleep 1
  curl -sS -X POST http://127.0.0.1:5050/api/_inter-agent/ingest \
       -H Content-Type:application/json \
       -d \"{\\\"scenario_id\\\":\\\"demo-5\\\",\\\"phase\\\":\\\"done\\\",
             \\\"correlation_id\\\":\\\"\$corr\\\",
             \\\"from_host\\\":\\\"ares-comp-11\\\",\\\"from_session\\\":\\\"planner\\\",
             \\\"to_host\\\":\\\"ares-comp-16\\\",\\\"to_session\\\":\\\"executor\\\",
             \\\"status\\\":\\\"ok\\\",\\\"latency_ms\\\":312.0}\"
"'
```

**What you should see in the UI:**

```
Tab Scenarios → click demo-5

  ┌─── ares-comp-11 ────┐                    ┌─── ares-comp-16 ────┐
  │   ┌───────────┐    │                    │   ┌───────────┐    │
  │   │ planner   │    │ delegate_to_       │   │ executor  │    │
  │   │ 22 turns  │ ───┼──── executor   ────┼─► │ 15 turns  │    │
  │   │ 5 sub     │    │  (312ms ✓)         │   │ 5 sub     │    │
  │   └───────────┘    │                    │   └───────────┘    │
  └─────────────────────┘                    └─────────────────────┘

Tab Workspace → click row "planner" → expand:
  • Turn 1: Bash(hostname, pwd)            ← tool call
  • Turn 2: Read(/etc/os-release)          ← tool call
  • Turn 3: Task(general-purpose, "name 2...")  ← spawns sub-session planner.2
    └─ planner.2: subagent system+user → response
  • Turn 4-5: synthesize + reply           ← final assistant message
```

### 6.3 Demo-6 — same shape but the subagents themselves use tools

Same scenario template, but the prompts force the Task subagents to invoke
Bash inside their own context. This produces deeper sub-session trees
(`planner.2`, `planner.3`, ..., up to `planner.10` in our run) and more
realistic Workspace depth.

```bash
# planner — Task subagent runs `df -h /tmp` itself
claude --permission-mode bypassPermissions --max-turns 8 -p "
  Planner agent.
  Step1 Bash hostname.
  Step2 Read /etc/hostname.
  Step3 Task subagent_type=general-purpose:
        'Use Bash to run df -h /tmp | tail -1, return one short line.'
  Step4 1-sentence wrap-up."

# executor — Task subagent runs `free -h` itself
claude --permission-mode bypassPermissions --max-turns 8 -p "
  Executor agent.
  Step1 Bash hostname.
  Step2 Bash uptime.
  Step3 Task subagent_type=general-purpose:
        'Use Bash to run free -h | head -2, return one short line.'
  Step4 1-sentence wrap-up."
```

**Result of an actual demo-6 run:**

| Agent | Host | Interactions | Sub-sessions | Tokens |
|---|---|---:|---|---:|
| `planner` | ares-comp-11 | 39 | 10 (planner, .2 … .10) | 2033 |
| `executor` | ares-comp-16 | 20 | 8 (executor, .2 … .8) | 1424 |
| edge | planner → executor (`delegate_to_executor`, 268ms) | | | |

The 10 sub-sessions per agent reflect claude's Task tool spawning subagents,
plus the agent SDK's internal pre-fetch / cache-priming workers. From the
Workspace tab you can drill into each `.N` node to see exactly what that
subagent saw and produced.

### 6.4 Rate-limit pacing

Anthropic enforces a per-org **input-tokens-per-minute** budget (10K for our
demo org). Each `claude -p` invocation with the Task tool consumes ~10–15K
input tokens (parent system prompt + Task tool definitions + spawned subagent
system prompt + user message). Two heavy calls back-to-back will trigger 429.

**Pacing rule used for demo-6:** wait ≥ 30 s between heavy calls; the bucket
refills enough to allow the next one. If a Task subagent itself hits 429, the
parent treats it as a tool failure and continues — the data is still recorded;
only the subagent's body is the rate-limit error message.

---

## 7. How to author your own scenario

### Checklist (must-do, in order)

1. **Pick a scenario id.** Lowercase kebab-case, unique per run. Example:
   `expt-routing-2026-04-24a`.
2. **Decide the topology.** N peer agents on M hosts; for each peer agent:
   its base session id, its host, what tools it should exercise, what
   subagents it should spawn.
3. **Write the URL for each peer.** Always include `/_host/<HOST>/` and
   `/_scenario/<SID>/` from interaction #1. Skipping `/_host/` poisons the
   host attribution permanently.
4. **Allocate the SLURM nodes.** One `salloc -N 1 --no-shell` per host; use
   `--exclude=` to land on different physical nodes.
5. **Fire the LLM traffic.** `srun -N1 -n1 -w <host> --overlap --jobid=<job>
   env ... claude -p "..."`. Pace by ≥30 s between heavy calls.
6. **Post the inter-agent edges** with `curl POST /api/_inter-agent/ingest`,
   one start/done pair per cross-agent call. Choose a correlation_id; the same
   id must appear on both events.
7. **Verify** with `curl /api/scenarios/<sid>/graph` — agents should have
   non-empty `host` and non-zero `interaction_count`; edges should have your
   chosen tool_name, status, latency.

### Production path: don't curl — use the MCP relay

The manual `curl` for ingest is fine for demos. In production, the **inter-agent
relay** at `context-exploration-engine/agent-interceptor/inter_agent_relay/`
exposes an MCP server that any agent can `mcp_call` to. The relay
auto-generates a correlation_id, posts `start` immediately, executes the call
to the remote agent, and posts `done` with status+latency on completion. You
don't have to think about ingest at all — you just expose the relay as an MCP
server in your agent's config and call its `call_remote_agent` tool.

---

## 8. Pitfalls & lessons (read these before debugging)

| # | Pitfall | Fix |
|---:|---|---|
| 1 | `/_host/<H>/` missing on first call → agent pinned to wrong host forever | Always include URL prefix from call #1; if poisoned, use a fresh scenario id |
| 2 | `dt_demo_server` restart wipes all `interaction_count` and tokens | Treat dt as in-memory; re-fire smoke after any restart. Edges survive (Flask-side store) |
| 3 | `srun bash -c '… nohup … &'` kills the daemon when the step exits | Use plain `ssh <node> '… nohup … &'` for long-running services |
| 4 | `pam_slurm_adopt` rejects SSH when you have multiple SLURM jobs | Bypass with `srun --jobid=<N> -w <node>` |
| 5 | Anthropic rate limit (10K input tokens/min) trips heavy multi-tool prompts | Pace ≥30 s between calls; 429 on a Task subagent is non-fatal (parent gets a tool error and continues) |
| 6 | Chrome blocks "unsafe ports" (5060, 6000, 6665-9, ...) | Use ports in [8050, 8888] or 18000+ for `ssh -L` |
| 7 | Mac VS Code grabs random local ports → `ssh -L bind ... in use` | Pick a high port (18051 worked); kill stray ssh tunnels with `pkill -f "ssh.*-L"` |
| 8 | C++ edits in the live repo don't show up in `dt_demo_server` builds | rattler-build snapshots the source; sync edited files into `rattler-build_iowarp-core_*/work/` before `cmake --build` |

Memory entries that capture each in detail:
- `feedback_scenario_url_prefix.md`
- `project_dt_restart_wipes_llm.md`
- `project_workspace_viz_port_state.md`
- `project_rattler_scratch_source.md`

---

## 9. Code references

### Backend (Python — Flask)

| Path | Role |
|---|---|
| `context_visualizer/api/llm_dispatch.py:430-455` | URL prefix routes for `/_host/`, `/_scenario/`, `/_session/` |
| `context_visualizer/api/llm_dispatch.py:458-512` | `_forward_request_impl` — stamps host+scenario, forwards via Chimaera |
| `context_visualizer/api/inter_agent.py:52-134` | `POST /api/_inter-agent/ingest` — edge ingest |
| `context_visualizer/api/inter_agent.py:142-176` | `GET /api/scenarios/<sid>/inter-agent[/raw]` — edge reads |
| `context_visualizer/adapters/scenario_adapter.py:33-84` | `_peer_bundle` — agent rollup with most-frequent-host vote |
| `context_visualizer/adapters/scenario_adapter.py:98-150` | `build_scenario_graph` — agents + edges → ScenarioGraph |
| `context_visualizer/adapters/scenario_adapter.py:153-182` | `build_scenario_summary` — lightweight list for `/api/scenarios` |
| `context_visualizer/inter_agent/store.py` | `InterAgentStore` — Flask-side persistence + start/done stitching |

### Backend (C++ — proxy + tracker chimods)

| Path | Role |
|---|---|
| `context-exploration-engine/agent-interceptor/interception/anthropic/src/anthropic_runtime.cc` | Anthropic chimod entry, sets up MITM proxy |
| `context-exploration-engine/agent-interceptor/interception/{openai,ollama}/src/*.cc` | Sibling provider chimods |
| `context-exploration-engine/agent-interceptor/interception/.../src/proxy_runtime.cc::BuildInteractionRecord` | Builds the `InteractionRecord` from each request/response — this is where commit `fabc2a79` added `record.timestamp` |
| `context-exploration-engine/agent-interceptor/tracker/src/tracker_runtime.cc` | Aggregates records into per-tag CTE blobs |

### Frontend (React)

| Path | Role |
|---|---|
| `context-visualizer/frontend/src/components/workspace/` | Workspace tab — per-conversation timeline, tool tree |
| `context-visualizer/frontend/src/components/scenarios/` | Scenarios tab — host rectangles, agent nodes, edge arrows, hue map |
| `context-visualizer/frontend/src/hooks/useConversationData.ts` | Pulls `/api/conversations` + per-session interactions |
| `context-visualizer/frontend/src/hooks/useScenarios.ts` | Pulls `/api/scenarios` + `/api/scenarios/<sid>/graph` |

### Demo / smoke scripts

| Path | Role |
|---|---|
| `context-visualizer/scripts/smoke-multiagent.sh` | 4-test smoke (basic, multiturn, tools, fanout) — single host |
| `context-visualizer/scripts/smoke-multi-agent-peers.sh` | 2-host peer scenario with `srun` real-nodes mode (`DTP_REAL_NODES=1`) |
| `context-visualizer/scripts/test-call-graph.sh` | Direct call-graph verifier |

---

*Last updated: 2026-04-24, against branch `port/workspace-from-reference`
@ commit `57b409b9`.*
