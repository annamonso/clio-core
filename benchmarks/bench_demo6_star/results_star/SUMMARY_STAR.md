# bench_demo6_star — Test 5 (distributed star topology)

- Total runs in `runs.jsonl`: **8** (success=7, hard-failed=1, rate-limit soft-failed=0)
- Per-config counts: star1=4, star3=4
- Cumulative estimated cost: **$0.032**

## Topology

- **star1**: 1 controller (harness-driven, no `claude -p`) → 1 worker (`claude -p` running demo-6's executor prompt).
- **star3**: 1 controller → 3 workers in parallel (`ThreadPoolExecutor` fan-out). Each worker is on its own SLURM-allocated compute node.

## Methodology notes

- **Parallel fan-out.** Workers are dispatched concurrently via `concurrent.futures.ThreadPoolExecutor(max_workers=N)`; each thread issues a blocking `srun --jobid=… -w <worker_host> claude -p`. After all workers return, edge `start` POSTs are fired in parallel from the controller node (`srun -w <controller_host> curl …`) — that's what the per-edge latency rows measure.
- **Edge latency.** Same caveat as bench_demo6: `/api/_inter-agent/ingest` stores caller-supplied `latency_ms`, it does not measure. This harness substitutes the measured curl RTT, then closes the pair with an untimed `done` POST.
- **Session-id discipline.** Per multi-agent-visualization.md §8 pitfall #1, every worker uses a session id of the form `worker{N}-{scenario_id}` — unique across runs (avoids `_peer_bundle` collapse) AND unique among the 3 workers within a single run (avoids fan-out merge).
- **Host attribution.** `_host/<H>` URL prefix is set from the worker's assigned node. The audit below checks the graph's `agent.host` field matches expectation.
- **Rate-limit soft fail.** Any worker with `interaction_count ≤ 2` marks the run as soft-fail (run not counted, no retry, +60 s pacing).
- **Cost estimate.** `total_tokens` from the graph multiplied by Sonnet 4-6 list rates, assuming an 80/20 input/output split (graph doesn't expose direction breakdown). Real billing is in the console.

## Per-config tables

### star1 (N=4 successful runs)

| metric | P50 / P90 / max / stdev |
|---|---|
| wall_time_s (full run) | 24.70 s / 81.77 s / 105.23 s / 40.92 s |
| workers_wall_s_max (critical-path fan-out) | 22.05 s / 79.21 s / 102.64 s / 40.96 s |
| workers_wall_s_sum (would-be-serial baseline) | 22.05 s / 79.21 s / 102.64 s / 40.96 s |
| edges_latency_ms_max (slowest of 1) | 20.95 ms / 35.34 ms / 35.83 ms / 15.85 ms |
| per-edge edge_latency_ms (across all workers × runs, n=4) | 20.95 ms / 35.34 ms / 35.83 ms / 15.85 ms |
| total tokens per run (sum across workers) | 1040.00 / 1078.00 / 1093.00 / 39.37 |
| total interaction_count per run (sum across workers) | 6.00 / 14.40 / 18.00 / 6.18 |
| estimated cost per run (USD) | 0.01 / 0.01 / 0.01 / 0.00 |

**Host-attribution accuracy:** 4/4 worker→host pairs matched (100.0%).

### star3 (N=3 successful runs)

| metric | P50 / P90 / max / stdev |
|---|---|
| wall_time_s (full run) | 62.97 s / 70.75 s / 72.70 s / 8.67 s |
| workers_wall_s_max (critical-path fan-out) | 54.34 s / 56.68 s / 57.27 s / 3.19 s |
| workers_wall_s_sum (would-be-serial baseline) | 143.89 s / 159.15 s / 162.97 s / 11.25 s |
| edges_latency_ms_max (slowest of 3) | 9.35 ms / 10.73 ms / 11.07 ms / 1.19 ms |
| per-edge edge_latency_ms (across all workers × runs, n=9) | 9.16 ms / 10.95 ms / 11.07 ms / 2.00 ms |
| total tokens per run (sum across workers) | 3017.00 / 3069.00 / 3082.00 / 62.52 |
| total interaction_count per run (sum across workers) | 18.00 / 18.00 / 18.00 / 0.58 |
| estimated cost per run (USD) | 0.02 / 0.02 / 0.02 / 0.00 |

**Host-attribution accuracy:** 9/9 worker→host pairs matched (100.0%).

## star1 vs star3 — head-to-head (P50 medians)

| metric | star1 | star3 | star3/star1 |
|---|---|---|---|
| wall_time_s (full run) | 24.70 s | 62.97 s | 2.55× |
| workers_wall_s_max (critical path) | 22.05 s | 54.34 s | 2.46× |
| per-edge latency | 20.95 ms | 9.16 ms | 0.44× |
| total tokens per run | 1040 | 3017 | 2.90× |
| estimated cost per run | $0.0056 | $0.0163 | 2.90× |

**Interpretation guide (numbers above, not commentary):**
- A `star3/star1` ratio < 3.0× on wall_time_s indicates the parallel fan-out amortized would-be-serial work.
- A `star3/star1` ratio > 1.0× on per-edge latency indicates the leader's `/api/_inter-agent/ingest` path serialized 3 concurrent POSTs (Werkzeug single-threaded handler bottleneck).
- A `star3/star1` ratio ≈ 3.0× on total tokens reflects the 3× more claude `-p` invocations in star3.

## Host-attribution audit (Pitfall #1 stress under fan-out)

Demo-6 docs §8 pitfall #1: `_host/<H>` URL prefix must be present from interaction #1 or `scenario_adapter._peer_bundle` pins the agent to the wrong host permanently. star3 runs 3 concurrent edge POSTs from a single controller node — this audit checks each worker landed on its assigned host in the resulting graph.

**On successful runs:** 13/13 worker→host pairs matched (100.0%) — **0 real drift events.**
**On failed runs:** 3 (worker × run) pair(s) had no observed host (graph fetch failed before attribution could be made). These are missing-data, NOT drift.

| scenario_id | config | worker | assigned | observed | status |
|---|---|---|---|---|---|
| star1-smoke-1777241161 | star1 | w1 | ares-comp-14 | ares-comp-14 | ✓ |
| star3-smoke-1777241284 | star3 | w1 | ares-comp-14 | ares-comp-14 | ✓ |
| star3-smoke-1777241284 | star3 | w2 | ares-comp-15 | ares-comp-15 | ✓ |
| star3-smoke-1777241284 | star3 | w3 | ares-comp-16 | ares-comp-16 | ✓ |
| star1-001 | star1 | w1 | ares-comp-14 | ares-comp-14 | ✓ |
| star1-002 | star1 | w1 | ares-comp-14 | ares-comp-14 | ✓ |
| star1-003 | star1 | w1 | ares-comp-14 | ares-comp-14 | ✓ |
| star3-001 | star3 | w1 | ares-comp-14 | ares-comp-14 | ✓ |
| star3-001 | star3 | w2 | ares-comp-15 | ares-comp-15 | ✓ |
| star3-001 | star3 | w3 | ares-comp-16 | ares-comp-16 | ✓ |
| star3-002 | star3 | w1 | ares-comp-14 | ares-comp-14 | ✓ |
| star3-002 | star3 | w2 | ares-comp-15 | ares-comp-15 | ✓ |
| star3-002 | star3 | w3 | ares-comp-16 | ares-comp-16 | ✓ |
| star3-003 | star3 | w1 | ares-comp-14 | — | — (run failed, no graph data) |
| star3-003 | star3 | w2 | ares-comp-15 | — | — (run failed, no graph data) |
| star3-003 | star3 | w3 | ares-comp-16 | — | — (run failed, no graph data) |
