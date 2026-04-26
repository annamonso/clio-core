"""One end-to-end demo-6 invocation. Reads SLURM/host config from env.

Required env vars (no defaults baked in — caller must export):
    LEADER_HOST       e.g. "ares-comp-11"   — Flask + dt_demo_server node
    LEADER_PORT       e.g. "5050"
    LEADER_JOB        SLURM jobid for the leader allocation
    PEER_HOST         e.g. "ares-comp-16"   — used in two-host configs
    PEER_JOB          SLURM jobid for the peer allocation
    ANTHROPIC_API_KEY

Optional:
    BENCH_PACE_S        default 30 (caller-driven; not slept here)
    BENCH_RUN_TIMEOUT_S default 600 per claude invocation
    BENCH_INGEST_TIMEOUT_S default 60 per ingest curl
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.request
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

# Demo-6 prompts — verbatim from multi-agent-visualization.md §6.3.
# Payload size is one variable per sweep: it travels only in the cross-host
# POST body, never in the planner prompt.
PLANNER_PROMPT = (
    "Planner agent.\n"
    "Step1 Bash hostname.\n"
    "Step2 Read /etc/hostname.\n"
    "Step3 Task subagent_type=general-purpose: "
    "'Use Bash to run df -h /tmp | tail -1, return one short line.'\n"
    "Step4 1-sentence wrap-up."
)

EXECUTOR_PROMPT = (
    "Executor agent.\n"
    "Step1 Bash hostname.\n"
    "Step2 Bash uptime.\n"
    "Step3 Task subagent_type=general-purpose: "
    "'Use Bash to run free -h | head -2, return one short line.'\n"
    "Step4 1-sentence wrap-up."
)

DEFAULT_PAYLOAD_TEXT = "need executor to gather memory and uptime info"

# Rate-limit detection threshold. A clean demo-6 run produces 6+ interactions
# per agent; ≤2 on both is the rate-limited signature (each agent did one or
# two LLM calls before its subagent's 429 cascaded to a tool-failure return).
RATE_LIMIT_INT_THRESHOLD = 2

# Lorem-ipsum-style filler. Repeated to hit target sizes for Sweep B.
_LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim "
    "veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea "
    "commodo consequat. Duis aute irure dolor in reprehenderit in voluptate "
    "velit esse cillum dolore eu fugiat nulla pariatur. "
)


@dataclass
class HostConfig:
    """Where each peer runs. Set executor_host == planner_host for single-host."""
    planner_host: str
    executor_host: str
    planner_job: str
    executor_job: str


@dataclass
class RunConfig:
    scenario_id: str
    sweep: str                         # "a" | "b" | "c"
    payload_size_bytes: int            # 0 → use DEFAULT_PAYLOAD_TEXT verbatim
    host_config: HostConfig
    run_timeout_s: int = 600
    ingest_timeout_s: int = 60


@dataclass
class RunResult:
    scenario_id: str
    sweep: str
    config: dict
    success: bool
    fail_reason: str = ""
    retry_count: int = 0
    wall_time_s: float = 0.0
    planner_wall_s: float = 0.0
    executor_wall_s: float = 0.0
    edge_latency_ms: float = 0.0       # measured RTT of cross-host start POST
    edge_post_status: int = 0
    planner_interactions: int = 0
    executor_interactions: int = 0
    planner_tokens: int = 0
    executor_tokens: int = 0
    planner_host_observed: str = ""    # most-frequent-host vote per scenario_adapter
    executor_host_observed: str = ""
    payload_actual_bytes: int = 0
    ts_start: str = ""
    ts_done: str = ""
    extra: dict = field(default_factory=dict)

    def to_jsonl_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":")) + "\n"


# ─── env helpers ─────────────────────────────────────────────────────────────

def _require_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"{name} is not set in env")
    return v


def leader_url() -> str:
    return f"http://{_require_env('LEADER_HOST')}:{_require_env('LEADER_PORT')}"


# ─── payload construction ───────────────────────────────────────────────────

def pad_payload(target_size_bytes: int) -> str:
    """Lorem-ipsum padded to exactly target_size_bytes. 0 → default short text."""
    if target_size_bytes <= 0:
        return DEFAULT_PAYLOAD_TEXT
    base = DEFAULT_PAYLOAD_TEXT + " "
    if len(base.encode("utf-8")) >= target_size_bytes:
        return base.encode("utf-8")[:target_size_bytes].decode("utf-8", errors="ignore")
    repeats = (target_size_bytes // len(_LOREM)) + 1
    filler = (_LOREM * repeats)
    out = (base + filler).encode("utf-8")[:target_size_bytes]
    return out.decode("utf-8", errors="ignore")


# ─── server health / restart detection ──────────────────────────────────────

def _http_get_json(url: str, timeout: float = 5.0) -> Optional[dict | list]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _ssh_dt_pid() -> Optional[int]:
    """Authoritative: dt_demo_server PID on LEADER_HOST via SSH.

    Returns None on SSH failure or if the process is not running. Used as the
    sole signal for "did the server restart?" — a transient Flask slow-response
    is NOT a restart, and earlier heuristics (conv-count drops) were unreliable
    because session names like 'planner' collide on base session id across
    scenarios so the count doesn't grow per run.
    """
    leader = os.environ.get("LEADER_HOST", "").strip()
    if not leader:
        return None
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
             "-o", "StrictHostKeyChecking=no", leader,
             "pgrep -f dt_demo_server | head -1"],
            capture_output=True, timeout=15,
        )
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        return int(out) if out.isdigit() else None
    except Exception:
        return None


def _flask_reachable(retries: int = 3, per_try_timeout: float = 10.0) -> bool:
    """Probe Flask /api/conversations. Tolerate transient slowness — Flask gets
    busy right after a heavy claude invocation finishes; one slow response is
    not a server failure."""
    base = leader_url()
    for i in range(retries):
        try:
            req = urllib.request.Request(f"{base}/api/conversations")
            with urllib.request.urlopen(req, timeout=per_try_timeout) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        if i < retries - 1:
            time.sleep(2)
    return False


def health_snapshot() -> dict:
    """Authoritative health snapshot.

    `dt_pid` is the only durable identifier for a dt_demo_server lifecycle —
    if it changes between sweep checkpoints, the in-memory CTE blob storage
    (Path A) was wiped (per multi-agent-visualization.md §8 pitfall #2).
    Edges (Path B, Flask-side) survive a dt restart.
    """
    pid = _ssh_dt_pid()
    flask_ok = _flask_reachable()
    return {
        "ok": flask_ok and pid is not None,
        "dt_pid": pid,
        "flask_ok": flask_ok,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def server_restarted(prev: dict, curr: dict) -> bool:
    """Definitive restart signal: dt_demo_server PID changed.

    Transient flake (curr.flask_ok=False but PID unchanged) is NOT a restart —
    we tolerate it and let the next per-run health check catch a real outage.
    Only when we have a confirmed PID on both sides AND they differ do we
    declare the server restarted and abort the sweep.
    """
    p_prev = prev.get("dt_pid")
    p_curr = curr.get("dt_pid")
    if p_prev and p_curr and p_prev != p_curr:
        return True
    return False


# ─── claude driver ──────────────────────────────────────────────────────────

def _no_proxy_value() -> str:
    leader = os.environ.get("LEADER_HOST", "")
    peer = os.environ.get("PEER_HOST", "")
    parts = ["localhost", "127.0.0.1", "ares"]
    if leader:
        parts.append(leader)
    if peer and peer != leader:
        parts.append(peer)
    return ",".join(parts)


def _build_anthropic_base_url(host: str, scenario_id: str, session: str) -> str:
    """Compose the URL with /_host/<H>/_scenario/<S>/_session/<X> prefix.

    CRITICAL — Pitfall #1 in multi-agent-visualization.md §8: the /_host/ prefix
    must be present from interaction #1 or scenario_adapter._peer_bundle's
    most-frequent-host vote pins the agent to the wrong host permanently.
    """
    return f"{leader_url()}/_host/{host}/_scenario/{scenario_id}/_session/{session}"


def drive_agent(
    *,
    host: str,
    job: str,
    scenario_id: str,
    session: str,
    prompt: str,
    api_key: str,
    timeout_s: int,
) -> tuple[bool, float, str]:
    """Run one `claude -p` on `host` via srun. Return (success, wall_s, stderr)."""
    base_url = _build_anthropic_base_url(host, scenario_id, session)
    no_proxy = _no_proxy_value()
    home = os.environ.get("HOME", "")
    env_str = (
        f"PATH={home}/.local/bin:/usr/bin:/bin "
        f"ANTHROPIC_API_KEY={shlex.quote(api_key)} "
        f"ANTHROPIC_BASE_URL={shlex.quote(base_url)} "
        f"no_proxy={no_proxy} NO_PROXY={no_proxy}"
    )
    cmd = [
        "srun", "-N1", "-n1", "-w", host, "--overlap", f"--jobid={job}",
        "bash", "-lc",
        f"env {env_str} claude --permission-mode bypassPermissions --max-turns 8 "
        f"-p {shlex.quote(prompt)}",
    ]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        return False, time.monotonic() - t0, f"timeout after {timeout_s}s: {exc}"
    wall = time.monotonic() - t0
    if proc.returncode != 0:
        err_tail = proc.stderr.decode("utf-8", errors="replace")[-2000:]
        return False, wall, f"exit={proc.returncode}\n{err_tail}"
    return True, wall, ""


# ─── timed cross-host ingest POST (Sweep B's measurement primitive) ─────────

def time_cross_host_start(
    *,
    from_host: str,
    from_session: str,
    to_host: str,
    to_session: str,
    scenario_id: str,
    correlation_id: str,
    payload: str,
    peer_job: str,
    timeout_s: int,
) -> tuple[bool, float, int, str]:
    """POST 'start' from `from_host` (executor side) to leader's ingest endpoint,
    timing the round-trip with curl's %{time_total}.

    For single-host configs (from_host == LEADER_HOST), this is a localhost POST
    and serves as the same-host control.

    Returns (success, latency_ms, http_status, stderr).
    """
    body = {
        "scenario_id": scenario_id,
        "phase": "start",
        "correlation_id": correlation_id,
        "from_host": from_host,
        "from_session": from_session,
        "to_host": to_host,
        "to_session": to_session,
        "kind": "mcp_call",
        "tool_name": "delegate_to_executor",
        "payload": payload,
    }
    body_bytes = json.dumps(body).encode("utf-8")
    url = f"{leader_url()}/api/_inter-agent/ingest"
    no_proxy = _no_proxy_value()

    # `--data-binary @-` reads the body from stdin so we don't have to escape
    # the JSON inside the remote shell.
    remote = (
        f"curl -sS --noproxy '*' --max-time {timeout_s} -o /dev/null "
        f"-w '%{{http_code}} %{{time_total}}' "
        f"-X POST {shlex.quote(url)} "
        f"-H 'Content-Type: application/json' "
        f"-H 'X-No-Proxy: 1' "
        f"--data-binary @-"
    )
    cmd = [
        "srun", "-N1", "-n1", "-w", from_host, "--overlap", f"--jobid={peer_job}",
        "bash", "-lc",
        f"export no_proxy={no_proxy} NO_PROXY={no_proxy}; {remote}",
    ]
    try:
        proc = subprocess.run(
            cmd, input=body_bytes, capture_output=True, timeout=timeout_s + 30
        )
    except subprocess.TimeoutExpired as exc:
        return False, 0.0, 0, f"ingest timeout: {exc}"
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    err = proc.stderr.decode("utf-8", errors="replace")[-1000:]
    if proc.returncode != 0 or not out:
        return False, 0.0, 0, f"srun/curl exit={proc.returncode}: {err}"
    parts = out.split()
    if len(parts) != 2:
        return False, 0.0, 0, f"unparsable curl -w output: {out!r}"
    try:
        status = int(parts[0])
        latency_ms = float(parts[1]) * 1000.0
    except ValueError:
        return False, 0.0, 0, f"parse failure: {out!r}"
    if status < 200 or status >= 300:
        return False, latency_ms, status, f"non-2xx: {status}"
    return True, latency_ms, status, ""


def post_done(
    *,
    scenario_id: str,
    correlation_id: str,
    from_host: str,
    from_session: str,
    to_host: str,
    to_session: str,
    latency_ms: float,
    status_label: str,
    timeout_s: int = 30,
) -> tuple[bool, str]:
    """Local 'done' POST from leader, untimed. Closes the start/done pair."""
    body = {
        "scenario_id": scenario_id,
        "phase": "done",
        "correlation_id": correlation_id,
        "from_host": from_host,
        "from_session": from_session,
        "to_host": to_host,
        "to_session": to_session,
        "status": status_label,
        "latency_ms": latency_ms,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{leader_url()}/api/_inter-agent/ingest",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if resp.status >= 300:
                return False, f"done HTTP {resp.status}"
    except Exception as exc:
        return False, f"done POST exception: {exc}"
    return True, ""


# ─── graph fetch ────────────────────────────────────────────────────────────

def fetch_scenario_graph(scenario_id: str, timeout_s: int = 30) -> Optional[dict]:
    """Fetch /api/scenarios/<sid>/graph. 30s default tolerates Werkzeug's single-
    threaded queue when Flask is mid-request on something else."""
    return _http_get_json(
        f"{leader_url()}/api/scenarios/{scenario_id}/graph", timeout=float(timeout_s)
    )


def _agent_by_id(graph: dict, agent_id: str) -> dict:
    for a in graph.get("agents", []):
        if a.get("agent_id") == agent_id:
            return a
    return {}


# ─── orchestrator: one_run ──────────────────────────────────────────────────

def one_run(cfg: RunConfig, results_dir: Path) -> RunResult:
    """Execute one demo-6 cycle. Persist per-run JSON immediately on success."""
    api_key = _require_env("ANTHROPIC_API_KEY")
    cid = f"{cfg.scenario_id}-{time.time_ns()}"
    payload = pad_payload(cfg.payload_size_bytes)

    res = RunResult(
        scenario_id=cfg.scenario_id,
        sweep=cfg.sweep,
        config={
            "payload_size_bytes": cfg.payload_size_bytes,
            "planner_host": cfg.host_config.planner_host,
            "executor_host": cfg.host_config.executor_host,
        },
        success=False,
        payload_actual_bytes=len(payload.encode("utf-8")),
        ts_start=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    t0 = time.monotonic()

    # Session ids are scenario-unique to prevent bundle collapse across runs.
    # scenario_adapter._peer_bundle (scenario_adapter.py:50) groups bundles by
    # base session id; using a literal "planner"/"executor" makes every run's
    # interactions accumulate into the SAME agent, so /api/scenarios/<sid>/graph
    # returns cumulative counts and eventually times out under load.
    plan_session = f"planner-{cfg.scenario_id}"
    exec_session = f"executor-{cfg.scenario_id}"

    # 1. Drive planner.
    ok, wall, err = drive_agent(
        host=cfg.host_config.planner_host,
        job=cfg.host_config.planner_job,
        scenario_id=cfg.scenario_id,
        session=plan_session,
        prompt=PLANNER_PROMPT,
        api_key=api_key,
        timeout_s=cfg.run_timeout_s,
    )
    res.planner_wall_s = wall
    if not ok:
        res.fail_reason = f"planner_exit_nonzero: {err[:500]}"
        res.wall_time_s = time.monotonic() - t0
        res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return res

    # 2. Drive executor.
    ok, wall, err = drive_agent(
        host=cfg.host_config.executor_host,
        job=cfg.host_config.executor_job,
        scenario_id=cfg.scenario_id,
        session=exec_session,
        prompt=EXECUTOR_PROMPT,
        api_key=api_key,
        timeout_s=cfg.run_timeout_s,
    )
    res.executor_wall_s = wall
    if not ok:
        res.fail_reason = f"executor_exit_nonzero: {err[:500]}"
        res.wall_time_s = time.monotonic() - t0
        res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return res

    # 3. Cross-host timed start POST (B1 measurement).
    ok, latency_ms, status_code, err = time_cross_host_start(
        from_host=cfg.host_config.executor_host,
        from_session=exec_session,
        to_host=cfg.host_config.planner_host,
        to_session=plan_session,
        scenario_id=cfg.scenario_id,
        correlation_id=cid,
        payload=payload,
        peer_job=cfg.host_config.executor_job,
        timeout_s=cfg.ingest_timeout_s,
    )
    res.edge_latency_ms = latency_ms
    res.edge_post_status = status_code
    if not ok:
        res.fail_reason = f"edge_post_non_2xx: {err[:500]}"
        res.wall_time_s = time.monotonic() - t0
        res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return res

    # 4. 'done' close-out (untimed, from leader).
    ok, err = post_done(
        scenario_id=cfg.scenario_id,
        correlation_id=cid,
        from_host=cfg.host_config.executor_host,
        from_session=exec_session,
        to_host=cfg.host_config.planner_host,
        to_session=plan_session,
        latency_ms=latency_ms,
        status_label="ok",
    )
    if not ok:
        res.fail_reason = f"edge_post_non_2xx (done): {err[:500]}"
        res.wall_time_s = time.monotonic() - t0
        res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return res

    # 5. Fetch graph + persist immediately (so an abort after this preserves it).
    graph = fetch_scenario_graph(cfg.scenario_id)
    if graph is None:
        res.fail_reason = "graph_fetch_failed"
        res.wall_time_s = time.monotonic() - t0
        res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return res

    results_dir.mkdir(parents=True, exist_ok=True)
    graph_path = results_dir / f"{cfg.scenario_id}.json"
    graph_path.write_text(json.dumps(graph, indent=2))

    planner_node = _agent_by_id(graph, plan_session)
    executor_node = _agent_by_id(graph, exec_session)
    res.planner_interactions = int(planner_node.get("interaction_count", 0))
    res.executor_interactions = int(executor_node.get("interaction_count", 0))
    res.planner_tokens = int(planner_node.get("total_tokens", 0))
    res.executor_tokens = int(executor_node.get("total_tokens", 0))
    res.planner_host_observed = planner_node.get("host", "")
    res.executor_host_observed = executor_node.get("host", "")

    res.success = True
    res.wall_time_s = time.monotonic() - t0
    res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Rate-limit soft-fail detection.
    # Anthropic enforces a per-org input-tokens-per-minute budget (10K on the
    # demo org). A demo-6 run uses ~10–15K input tokens; back-to-back runs at
    # tight pacing trip the limit on subagents (per multi-agent-visualization.md
    # §8 pitfall #5: the parent treats the subagent 429 as a tool failure and
    # continues, so the run completes "successfully" but with only 1–2
    # interactions per agent instead of the normal 6+). Treat that as a soft
    # fail: don't count it in analysis, don't retry (won't help — the budget is
    # already burnt), but make the surrounding pacing aware so the next run
    # starts cooler.
    if (res.planner_interactions <= RATE_LIMIT_INT_THRESHOLD
            and res.executor_interactions <= RATE_LIMIT_INT_THRESHOLD):
        res.success = False
        res.fail_reason = "rate_limited_soft_fail"

    return res
