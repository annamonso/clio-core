# bench_demo6_intra — Test 6 (intra-agent fan-out)

- Total runs in `runs.jsonl`: **10** (success=10, hard-failed=0, soft-failed=0)
- Per-N counts: N=1: 4, N=4: 3, N=10: 3
- Cumulative estimated cost: **$0.042**

## What this measures

One planner agent on a single host issues **N Bash tool calls in a single LLM turn** (parallel tool_use blocks dispatched concurrently by Claude Code's harness against a `sleep 1; echo …` shell). Vary N across {1, 4, 10}, n=3 each. The framework records each LLM turn as one `InteractionRecord` with nested `response.tool_calls: ToolCall[]` (see `protocol/include/dt_provenance/protocol/interaction.h:106`). There is no OpenTelemetry-style span tree; `parent_id` does not exist at the tool-call level. The questions answered here:

1. **Is the count preserved?** Does `len(response.tool_calls) == N`?
2. **Are the ids unique?** Each parallel tool emits a distinct `tool_use.id`. Verify the framework didn't dedup or overwrite under concurrency.
3. **Single-interaction containment?** All N Bash calls in *one* interaction record (the planner's first response), not split across turns.
4. **Did the SDK actually parallelize?** Wall-time math: parallel fan-out of N×1 s sleeps adds ~1 s to the run; serialized adds ~N s. The residual against the N=1 baseline answers this.

Wall-time interpretation: drive_agent wall ≈ (LLM turn 1 + tool phase + LLM turn 2 + harness overhead). The tool phase dominates the difference between N values.

## Per-N tables

### N=1 (n=4 successful runs)

| metric | P50 / P90 / max / stdev |
|---|---|
| wall_time_s (full run) | 11.03 s / 11.91 s / 12.21 s / 0.92 s |
| interactions (planner LLM turns) | 3.00 / 3.00 / 3.00 / 0.00 |
| Bash tool_calls captured | 1.00 / 1.00 / 1.00 / 0.00 |
| total tokens | 660.00 / 660.70 / 661.00 / 1.26 |
| estimated cost (USD) | 0.00 / 0.00 / 0.00 / 0.00 |

**Integrity (% of runs):** correct count=100%, all ids unique=100%, single-interaction containment=100%

**Parallelism verdict breakdown:** n_a=4


### N=4 (n=3 successful runs)

| metric | P50 / P90 / max / stdev |
|---|---|
| wall_time_s (full run) | 11.30 s / 11.42 s / 11.45 s / 0.24 s |
| interactions (planner LLM turns) | 3.00 / 3.00 / 3.00 / 0.00 |
| Bash tool_calls captured | 4.00 / 4.00 / 4.00 / 0.00 |
| total tokens | 811.00 / 839.00 / 846.00 / 20.50 |
| estimated cost (USD) | 0.00 / 0.00 / 0.00 / 0.00 |

**Integrity (% of runs):** correct count=100%, all ids unique=100%, single-interaction containment=100%

**Parallelism verdict breakdown:** parallel=3

**Wall residual vs N=1 baseline (P50):** 0.26 s — parallel-baseline expects ~1.0 s, serialized-baseline expects ~4.0 s.

### N=10 (n=3 successful runs)

| metric | P50 / P90 / max / stdev |
|---|---|
| wall_time_s (full run) | 14.12 s / 14.30 s / 14.34 s / 0.66 s |
| interactions (planner LLM turns) | 3.00 / 3.00 / 3.00 / 0.00 |
| Bash tool_calls captured | 10.00 / 10.00 / 10.00 / 0.00 |
| total tokens | 1154.00 / 1170.80 / 1175.00 / 45.40 |
| estimated cost (USD) | 0.01 / 0.01 / 0.01 / 0.00 |

**Integrity (% of runs):** correct count=100%, all ids unique=100%, single-interaction containment=100%

**Parallelism verdict breakdown:** parallel=3

**Wall residual vs N=1 baseline (P50):** 3.08 s — parallel-baseline expects ~1.0 s, serialized-baseline expects ~10.0 s.

## Failures + soft-fails

**Hard failures:** 0.  **Soft-fails (graph fetch):** 0.

_None._

## Bash-command shape audit

Sanity-check: every captured Bash tool call should start with `sleep `. **Runs with at least one off-shape command:** 0 of 10.

| scenario_id | N | sample bash commands (first 3) |
|---|---|---|
| intra-smoke-1777245616 | 1 | `sleep 1.0; echo tool_1_done` |
| intra-n1-001 | 1 | `sleep 1.0; echo tool_1_done` |
| intra-n1-002 | 1 | `sleep 1.0; echo tool_1_done` |
| intra-n1-003 | 1 | `sleep 1.0; echo tool_1_done` |
| intra-n4-001 | 4 | `sleep 1.0; echo tool_1_done · sleep 1.0; echo tool_2_done · sleep 1.0; echo tool_3_done` |
| intra-n4-002 | 4 | `sleep 1.0; echo tool_1_done · sleep 1.0; echo tool_2_done · sleep 1.0; echo tool_3_done` |
| intra-n4-003 | 4 | `sleep 1.0; echo tool_1_done · sleep 1.0; echo tool_2_done · sleep 1.0; echo tool_3_done` |
| intra-n10-001 | 10 | `sleep 1.0; echo tool_1_done · sleep 1.0; echo tool_2_done · sleep 1.0; echo tool_3_done` |
| intra-n10-002 | 10 | `sleep 1.0; echo tool_1_done · sleep 1.0; echo tool_2_done · sleep 1.0; echo tool_3_done` |
| intra-n10-003 | 10 | `sleep 1.0; echo tool_1_done · sleep 1.0; echo tool_2_done · sleep 1.0; echo tool_3_done` |
