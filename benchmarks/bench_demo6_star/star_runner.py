"""One end-to-end star-topology run. Reuses bench_demo6 primitives.

Star topology:
  controller (no claude -p; harness-driven from this node) → N workers (claude -p)

Required env (no defaults — caller must export):
    LEADER_HOST       e.g. "ares-comp-12"
    LEADER_PORT       e.g. "5050"
    LEADER_JOB        SLURM jobid for the leader allocation
    CONTROLLER_HOST   e.g. "ares-comp-13"   — node from which edge POSTs originate
    CONTROLLER_JOB    SLURM jobid (same allocation here)
    WORKER_HOSTS      comma-separated, e.g. "ares-comp-14,ares-comp-15,ares-comp-16"
    WORKER_JOB        SLURM jobid (same allocation here)
    ANTHROPIC_API_KEY

Optional:
    BENCH_RUN_TIMEOUT_S    default 600 per claude invocation
    BENCH_INGEST_TIMEOUT_S default 60 per ingest curl
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

# Reuse bench_demo6 primitives unchanged. Append (not prepend) so our local
# `analysis.py` wins over bench_demo6/analysis.py when bench.py imports it.
sys.path.append(str(Path(__file__).resolve().parent.parent / "bench_demo6"))
from runner import (  # noqa: E402
    EXECUTOR_PROMPT,
    DEFAULT_PAYLOAD_TEXT,
    _agent_by_id,
    drive_agent,
    fetch_scenario_graph,
    leader_url,
    pad_payload,
    post_done,
    time_cross_host_start,
)

# Rate-limit detection: any worker with interaction_count <= 2 → soft fail.
RATE_LIMIT_INT_THRESHOLD = 2

# Per-MTok cost estimates (Sonnet 4-6 list rates as of 2026-04). Used only for
# the budget cap — actual billing lives in the Anthropic console.
USD_PER_MTOK_IN = 3.0
USD_PER_MTOK_OUT = 15.0


# ─── data model ─────────────────────────────────────────────────────────────


@dataclass
class WorkerStat:
    label: str                    # "w1" / "w2" / "w3"
    assigned_host: str
    session_id: str
    correlation_id: str
    drive_ok: bool = False
    drive_wall_s: float = 0.0
    drive_err: str = ""
    edge_ok: bool = False
    edge_latency_ms: float = 0.0
    edge_status: int = 0
    edge_err: str = ""
    interaction_count: int = 0
    total_tokens: int = 0
    observed_host: str = ""
    host_match: bool = False


@dataclass
class StarRunConfig:
    scenario_id: str
    config: str                   # "star1" | "star3"
    leader_host: str
    leader_port: str
    leader_job: str
    controller_host: str
    controller_job: str
    worker_hosts: list[str]       # 1 or 3 entries
    worker_job: str
    payload_text: str
    run_timeout_s: int = 600
    ingest_timeout_s: int = 60


@dataclass
class StarRunResult:
    scenario_id: str
    config: str
    success: bool = False
    fail_reason: str = ""
    retry_count: int = 0
    wall_time_s: float = 0.0
    workers_wall_s_max: float = 0.0      # critical path of fan-out
    workers_wall_s_sum: float = 0.0      # would-be-serial baseline
    edges_latency_ms_max: float = 0.0
    edges_latency_ms_sum: float = 0.0
    workers: list[dict] = field(default_factory=list)
    payload_actual_bytes: int = 0
    estimated_cost_usd: float = 0.0      # this run alone
    cumulative_cost_usd_after: float = 0.0
    host_attribution_ok: bool = False
    host_attribution_warnings: list[str] = field(default_factory=list)
    ts_start: str = ""
    ts_done: str = ""
    extra: dict = field(default_factory=dict)

    def to_jsonl_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":")) + "\n"


# ─── orchestrator ────────────────────────────────────────────────────────────


def _drive_one_worker(
    *, cfg: StarRunConfig, ws: WorkerStat, api_key: str
) -> WorkerStat:
    ok, wall, err = drive_agent(
        host=ws.assigned_host,
        job=cfg.worker_job,
        scenario_id=cfg.scenario_id,
        session=ws.session_id,
        prompt=EXECUTOR_PROMPT,
        api_key=api_key,
        timeout_s=cfg.run_timeout_s,
    )
    ws.drive_ok = ok
    ws.drive_wall_s = wall
    ws.drive_err = err if not ok else ""
    return ws


def _post_one_edge(*, cfg: StarRunConfig, ws: WorkerStat) -> WorkerStat:
    """Fire the timed start POST from controller_host → leader, with this worker
    as the to_session. Untimed done POST closes the pair."""
    controller_session = f"controller-{cfg.scenario_id}"
    ok, latency_ms, status, err = time_cross_host_start(
        from_host=cfg.controller_host,
        from_session=controller_session,
        to_host=ws.assigned_host,
        to_session=ws.session_id,
        scenario_id=cfg.scenario_id,
        correlation_id=ws.correlation_id,
        payload=cfg.payload_text,
        peer_job=cfg.controller_job,
        timeout_s=cfg.ingest_timeout_s,
    )
    ws.edge_ok = ok
    ws.edge_latency_ms = latency_ms
    ws.edge_status = status
    ws.edge_err = err if not ok else ""
    if ok:
        # Untimed close-out (from leader, local POST). Best-effort; failure
        # here doesn't invalidate the timed measurement above.
        post_done(
            scenario_id=cfg.scenario_id,
            correlation_id=ws.correlation_id,
            from_host=cfg.controller_host,
            from_session=controller_session,
            to_host=ws.assigned_host,
            to_session=ws.session_id,
            latency_ms=latency_ms,
            status_label="ok",
        )
    return ws


def one_star_run(cfg: StarRunConfig, results_dir: Path) -> StarRunResult:
    """Execute one star-topology cycle.

    Pipeline:
      1. Fan-out workers in parallel (claude -p on each worker host).
      2. After all return, fan-out edge start POSTs in parallel from controller.
      3. Fetch graph, attribute per-worker stats + observed host.
      4. Apply rate-limit soft-fail check + host-attribution audit.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    res = StarRunResult(
        scenario_id=cfg.scenario_id,
        config=cfg.config,
        ts_start=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        payload_actual_bytes=len(cfg.payload_text.encode("utf-8")),
    )
    t0 = time.monotonic()

    workers: list[WorkerStat] = []
    for i, host in enumerate(cfg.worker_hosts):
        label = f"w{i+1}"
        workers.append(WorkerStat(
            label=label,
            assigned_host=host,
            # Session ids are scenario-unique (cross-run) AND label-unique
            # (within-run) — both protections required to avoid bundle collapse
            # under fan-out. See multi-agent-visualization.md §8 pitfall #1.
            session_id=f"worker{i+1}-{cfg.scenario_id}",
            correlation_id=f"{cfg.config}-{cfg.scenario_id}-{label}",
        ))

    # Phase 1: drive workers in parallel.
    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        futures = [pool.submit(_drive_one_worker, cfg=cfg, ws=w, api_key=api_key)
                   for w in workers]
        for f in futures:
            f.result()

    res.workers_wall_s_max = max((w.drive_wall_s for w in workers), default=0.0)
    res.workers_wall_s_sum = sum(w.drive_wall_s for w in workers)
    drive_failures = [w for w in workers if not w.drive_ok]
    if drive_failures:
        res.fail_reason = (
            "worker_drive_failed: "
            + "; ".join(f"{w.label}@{w.assigned_host}: {w.drive_err[:200]}"
                        for w in drive_failures)[:600]
        )
        res.workers = [asdict(w) for w in workers]
        res.wall_time_s = time.monotonic() - t0
        res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return res

    # Phase 2: fire edge start POSTs in parallel (controller → leader, one per worker).
    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        futures = [pool.submit(_post_one_edge, cfg=cfg, ws=w) for w in workers]
        for f in futures:
            f.result()

    res.edges_latency_ms_max = max((w.edge_latency_ms for w in workers), default=0.0)
    res.edges_latency_ms_sum = sum(w.edge_latency_ms for w in workers)
    edge_failures = [w for w in workers if not w.edge_ok]
    if edge_failures:
        res.fail_reason = (
            "edge_post_non_2xx: "
            + "; ".join(f"{w.label}: status={w.edge_status} {w.edge_err[:200]}"
                        for w in edge_failures)[:600]
        )
        res.workers = [asdict(w) for w in workers]
        res.wall_time_s = time.monotonic() - t0
        res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return res

    # Phase 3: fetch graph, attribute per-worker stats.
    graph = fetch_scenario_graph(cfg.scenario_id)
    if graph is None:
        res.fail_reason = "graph_fetch_failed"
        res.workers = [asdict(w) for w in workers]
        res.wall_time_s = time.monotonic() - t0
        res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return res

    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{cfg.scenario_id}.json").write_text(json.dumps(graph, indent=2))

    total_in = total_out = 0
    for w in workers:
        node = _agent_by_id(graph, w.session_id)
        w.interaction_count = int(node.get("interaction_count", 0))
        w.total_tokens = int(node.get("total_tokens", 0))
        w.observed_host = node.get("host", "") or ""
        w.host_match = (w.observed_host == w.assigned_host)
        # Conservative split for cost estimation: graph reports total_tokens
        # (input + output combined). Without per-direction breakdown, treat as
        # 80% input / 20% output — a typical short Bash-tool-call shape.
        total_in += int(w.total_tokens * 0.8)
        total_out += int(w.total_tokens * 0.2)
        if not w.host_match:
            res.host_attribution_warnings.append(
                f"{w.label}: assigned={w.assigned_host} observed={w.observed_host or '<missing>'}"
            )

    res.host_attribution_ok = (len(res.host_attribution_warnings) == 0)
    res.estimated_cost_usd = (
        (total_in / 1_000_000.0) * USD_PER_MTOK_IN
        + (total_out / 1_000_000.0) * USD_PER_MTOK_OUT
    )

    # Rate-limit soft-fail: any worker with interaction_count <= threshold.
    rate_limited = [w for w in workers if w.interaction_count <= RATE_LIMIT_INT_THRESHOLD]
    if rate_limited:
        res.fail_reason = (
            "rate_limited_soft_fail: "
            + ",".join(f"{w.label}(int={w.interaction_count})" for w in rate_limited)
        )
        res.success = False
    else:
        res.success = True

    res.workers = [asdict(w) for w in workers]
    res.wall_time_s = time.monotonic() - t0
    res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return res


# ─── helpers exported for bench.py ──────────────────────────────────────────


def is_soft_fail(res: StarRunResult) -> bool:
    return res.fail_reason.startswith("rate_limited_soft_fail")
