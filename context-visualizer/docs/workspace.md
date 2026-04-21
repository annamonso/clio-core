# Workspace View

## Why this view exists

The workspace view gives a clio-core user a playhead-driven, time-ordered view of
multi-agent handoffs across a parent + children session tree, with per-interaction
detail in a single pane. The existing call-graph page (`/call-graph`) is aggregate
and focused on a single session's call topology; the workspace shows the hand-off
sequence *across* agents — who called whom, in what order, with token and cost
totals per agent and a scrubbable timeline of the conversation. It is a replacement
for the agent-visualization and observability UI (the old `/call-graph`,
`/provenance`, and `/overhead` pages); the underlying provenance, checkpoint,
semantic, and overhead *APIs* remain unchanged and continue to serve every other
page.

Do not delete this view on the theory that `/call-graph` already covers it. The
two answer different questions:

- `/call-graph` — "for this one session, what did this agent call?"
- `/workspace`  — "across this conversation's agents, who handed off to whom
  and when?"

## Ports & conventions

- The view groups interactions by **base session id** (the portion of a
  `sid.N` or `sid.N.M` identifier before the first `.`). This is the
  "conversation id" in the React UI; no new column is written on clio-core
  interactions.
- Role inference: the base session is `orchestrator`; every descendant
  (`sid.N`, `sid.N.M`, ...) is `subagent`. Tool calls are not first-class
  graph nodes — they appear inside `DetailPanel`, matching the source
  behavior.
- Cost is computed client-side from `token_usage` against a small per-model
  price table in `frontend/src/lib/cost.ts`. Unknown models degrade to `—`.

## Parity check (manual smoke)

After wiring, run a small multi-agent scenario against the Chimaera runtime and
confirm the adapter agrees with existing provenance logic:

1. Pick a parent session id `<cid>` whose children also have interactions.
2. Call `compute_workflow_graph(...)` directly in Python with `scope=workflow`
   for `<cid>`.
3. Call `GET /api/conversations/<cid>/agent-graph` (the new adapter route).
4. Assert:
   - unique-session node count matches,
   - handoff edge count matches,
   - total interaction count across the graph equals
     `sum(len(interactions) for s in [parent, *children])`.

Any mismatch means the adapter is wrong; fix it before declaring the view
shipped.

## Ownership

Frontend tooling owner: **Anna**.

This owner is responsible for npm/Vite/Tailwind version bumps, lockfile hygiene,
and keeping `make workspace` reproducible in CI. If this line becomes stale
(ownership changes, etc.), update it — the view should not ship with no named
owner.
