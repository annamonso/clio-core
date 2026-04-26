# bench_demo6 — characterization summary

- Total runs in `runs.jsonl`: **33**  (success=22, hard-failed=10, rate-limit soft-failed=1)
- Per-sweep counts (raw): a=9, b=18, c=6
- Rate-limit soft-fails are excluded from all P50/P90/max/stdev calculations below — they reflect Anthropic's per-org token-rate limit (10K input tok/min on the demo org), not framework behavior.

## Methodology notes

- **Edge latency.** The framework's `/api/_inter-agent/ingest` endpoint stores caller-supplied `latency_ms` verbatim — it does not measure the cross-host call itself. This harness measures latency on its own POST round-trip from the executor host to the leader's ingest endpoint (carrying the padded payload), and substitutes that into the `done` event. Sweep A and Sweep B's `edge_latency_ms` are therefore real measured RTTs, not the framework's reported value of an unmeasured production call. Sweep C's `1h` configuration measures a localhost RTT.
- **Per-agent interaction_count and total_tokens** come from `/api/scenarios/<sid>/graph` and are sourced from the proxy's `InteractionRecord` blobs (Path A, in-memory). A `dt_demo_server` restart wipes these between runs; the harness aborts the sweep if it detects one.
- **wall_time_s** is the harness's monotonic-clock measurement of the full scenario: planner srun + executor srun + cross-host edge POST + graph fetch.
- **Pacing.** Flat 90 s between runs (≈8K input tok/min, under the demo org's 10K/min limit). 60 s pause + fresh `scenario_id` on retry. Rate-limited runs (`plan_int ≤ 2 AND exec_int ≤ 2`) are auto-classified as soft-fails, excluded from analysis, NOT retried, and trigger an extra 60 s cooldown before the next run. 429s on Task subagents are non-fatal per `multi-agent-visualization.md` §8 pitfall #5. Sweep B's 100 KB payload runs hit `graph_fetch_failed` retries due to Werkzeug single-thread bottlenecks (large POST + concurrent graph fetch); they succeed after retry but with higher tail wall-time.
- **Numbers, not interpretation.** P50 / P90 / max / stdev only.

## Sweep A — Variance (baseline, N=6 successful)

| metric | P50 / P90 / max / stdev |
|---|---|
| edge_latency_ms (cross-host start POST RTT) | 7.91 ms / 9.83 ms / 10.85 ms / 1.24 ms |
| wall_time_s (full scenario) | 101.51 s / 163.10 s / 166.37 s / 65.44 s |
| planner.interaction_count | 12.50 / 19.50 / 20.00 / 7.31 |
| executor.interaction_count | 6.00 / 6.00 / 6.00 / 0.52 |
| planner.total_tokens | 990.00 / 1014.00 / 1016.00 / 36.73 |
| executor.total_tokens | 1029.50 / 1056.00 / 1062.00 / 27.13 |

### Sweep A — edge_latency_ms distribution

```
  [    7.68 -     7.84]   3 | ##################################################
  [    7.84 -     7.99]   0 | 
  [    7.99 -     8.15]   1 | ################
  [    8.15 -     8.31]   0 | 
  [    8.31 -     8.47]   0 | 
  [    8.47 -     8.63]   0 | 
  [    8.63 -     8.79]   0 | 
  [    8.79 -     8.94]   1 | ################
  [    8.94 -     9.10]   0 | 
  [    9.10 -     9.26]   0 | 
  [    9.26 -     9.42]   0 | 
  [    9.42 -     9.58]   0 | 
  [    9.58 -     9.74]   0 | 
  [    9.74 -     9.90]   0 | 
  [    9.90 -    10.05]   0 | 
  [   10.05 -    10.21]   0 | 
  [   10.21 -    10.37]   0 | 
  [   10.37 -    10.53]   0 | 
  [   10.53 -    10.69]   0 | 
  [   10.69 -    10.85]   1 | ################
```

## Sweep B — Payload size (N=10 successful, B1 measurement)

**Measurement note (B1):** edge_latency_ms is the harness's measured round-trip time of the `start` POST issued from the executor host to the leader's `/api/_inter-agent/ingest` endpoint, with the padded payload in the request body. This is **not** the production MCP relay path — it characterizes payload-size sensitivity of the cross-host ingest path under controlled conditions.

**Limitation of the framework as observed:** `/api/_inter-agent/ingest` accepts `latency_ms` as a caller-supplied field (`inter_agent.py:99`). The framework does not measure edge latency itself; whatever the caller posts is what shows up in `/api/scenarios/<sid>/graph`. This harness substitutes a measured RTT, but in production deployments the field's reliability depends on the caller's instrumentation.

| payload_bytes | N | edge_latency P50 / P90 / max / stdev (ms) | wall_time P50 (s) |
|---:|---:|---|---:|
| 100 | 3 | 10.37 ms / 11.46 ms / 11.74 ms / 1.95 ms | 45.61 |
| 1000 | 3 | 7.46 ms / 7.63 ms / 7.67 ms / 0.14 ms | 71.89 |
| 10000 | 2 | 7.72 ms / 7.81 ms / 7.83 ms / 0.15 ms | 83.56 |
| 100000 | 2 | 9.56 ms / 10.30 ms / 10.48 ms / 1.30 ms | 65.57 |

## Sweep C — Single-host vs two-host (N=6 successful)

**Configurations.** `1h` = both planner and executor on `LEADER_HOST`; `2h` = planner on `LEADER_HOST`, executor on `PEER_HOST`. Same demo-6 workload in both. `edge_latency_ms` for `1h` is a localhost POST RTT and serves as the same-host control.

**What the 1h vs 2h delta isolates.** Both arms incur identical subprocess fork, `srun` setup, and Flask ingest-handler overhead — the only systematic difference between them is whether the POST traverses the cluster network or stays on loopback. The `edge_latency_ms` delta is therefore a measurement of the cluster network channel cost specifically, not a measurement of the broader cost of "running both agents on the same machine" (which would additionally entail CPU/memory contention effects that are not isolated by this design).

| config | N | wall_time P50/P90 (s) | edge_latency P50/P90 (ms) | planner.int_count P50 | executor.int_count P50 |
|---|---:|---|---|---:|---:|
| 1h (single-host) | 3 | 49.35 / 108.76 | 7.87 / 8.43 | 7 | 5 |
| 2h (two-host) | 3 | 71.06 / 85.72 | 7.67 / 8.01 | 7 | 6 |
