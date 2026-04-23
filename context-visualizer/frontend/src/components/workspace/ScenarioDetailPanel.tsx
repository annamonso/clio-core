import type { ScenarioEdge, ScenarioGraph } from "../../types";

export type DetailSelection =
  | { kind: "host"; host: string }
  | { kind: "edge"; edge: ScenarioEdge }
  | null;

interface Props {
  graph: ScenarioGraph;
  selection: DetailSelection;
  onClose: () => void;
  onOpenAgent: (agentId: string) => void;
}

/**
 * Same per-scenario-hue scheme as the ScenarioFlowGraph — evenly spaced
 * around the color wheel so the panel header matches the rectangle the
 * user just clicked. Derived from the scenario graph so both sides agree.
 */
function buildHostHueMap(hosts: Iterable<string>): Map<string, number> {
  const unique = Array.from(new Set(hosts)).sort();
  const step = 360 / Math.max(unique.length, 1);
  const offset = 200;
  const map = new Map<string, number>();
  unique.forEach((h, i) => {
    map.set(h, Math.round((offset + i * step) % 360));
  });
  return map;
}

function fmtTokens(n: number): string {
  if (!n) return "0";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function fmtCost(n: number): string {
  if (!n) return "$0";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function fmtLatency(ms: number): string {
  if (!ms) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function HostDetail({
  host,
  graph,
  onOpenAgent,
}: {
  host: string;
  graph: ScenarioGraph;
  onOpenAgent: (agentId: string) => void;
}) {
  const agents = graph.agents.filter((a) => (a.host || "unknown") === host);
  const outgoing = graph.edges.filter((e) => e.from_host === host);
  const incoming = graph.edges.filter((e) => e.to_host === host);

  const totalTokens = agents.reduce((s, a) => s + a.total_tokens, 0);
  const totalCost = agents.reduce((s, a) => s + a.total_cost_usd, 0);
  const totalInteractions = agents.reduce(
    (s, a) => s + a.interaction_count,
    0,
  );

  const peers = new Set<string>();
  for (const e of outgoing) peers.add(e.to_host || "unknown");
  for (const e of incoming) peers.add(e.from_host || "unknown");

  const hue =
    buildHostHueMap(graph.agents.map((a) => a.host || "unknown")).get(host) ?? 200;

  return (
    <>
      <header
        className="px-4 py-3 border-b border-border-soft"
        style={{
          backgroundColor: `hsl(${hue} 62% 48% / 0.06)`,
        }}
      >
        <div className="flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: `hsl(${hue} 62% 48%)` }}
          />
          <span className="text-[10px] uppercase tracking-widest text-fg-muted">
            node
          </span>
        </div>
        <div
          className="font-mono text-base font-semibold mt-0.5 truncate"
          style={{ color: `hsl(${hue} 62% 34%)` }}
          title={host}
        >
          {host || "unknown host"}
        </div>
      </header>

      <section className="px-4 py-3 border-b border-border-soft grid grid-cols-2 gap-y-2 gap-x-4 text-xs tabular-nums">
        <Stat label="Agents" value={agents.length.toString()} />
        <Stat label="Interactions" value={totalInteractions.toString()} />
        <Stat label="Tokens" value={fmtTokens(totalTokens)} />
        <Stat label="Cost" value={fmtCost(totalCost)} />
        <Stat label="Outgoing calls" value={outgoing.length.toString()} />
        <Stat label="Incoming calls" value={incoming.length.toString()} />
        <Stat
          label="Peer hosts"
          value={peers.size.toString()}
          title={Array.from(peers).join(", ")}
        />
      </section>

      <section className="px-4 py-3 border-b border-border-soft">
        <div className="text-[10px] uppercase tracking-widest text-fg-muted mb-2">
          Agents on this node
        </div>
        {agents.length === 0 ? (
          <div className="text-xs text-fg-muted">None</div>
        ) : (
          <ul className="flex flex-col gap-1">
            {agents.map((a) => (
              <li key={a.agent_id}>
                <button
                  type="button"
                  onClick={() => onOpenAgent(a.agent_id)}
                  className="w-full text-left px-2 py-1.5 rounded hover:bg-bg-elevated border border-transparent hover:border-border-soft"
                >
                  <div
                    className="font-mono text-xs truncate"
                    title={a.session_id}
                  >
                    {a.session_id}
                  </div>
                  <div className="text-[10px] text-fg-muted tabular-nums flex gap-2 mt-0.5">
                    <span>{a.interaction_count} call{a.interaction_count === 1 ? "" : "s"}</span>
                    <span>·</span>
                    <span>{fmtTokens(a.total_tokens)} tok</span>
                    {a.total_cost_usd > 0 && (
                      <>
                        <span>·</span>
                        <span>{fmtCost(a.total_cost_usd)}</span>
                      </>
                    )}
                  </div>
                  {a.sub_sessions.length > 1 && (
                    <div className="text-[10px] text-fg-muted mt-0.5">
                      {a.sub_sessions.length} sub-sessions
                    </div>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="px-4 py-3">
        <div className="text-[10px] uppercase tracking-widest text-fg-muted mb-2">
          Inter-agent calls
        </div>
        {outgoing.length === 0 && incoming.length === 0 ? (
          <div className="text-xs text-fg-muted">
            No cross-node communication recorded.
          </div>
        ) : (
          <div className="flex flex-col gap-2 text-xs">
            {outgoing.slice(0, 20).map((e) => (
              <EdgeRow key={`out-${e.event_id}-${e.ts_start ?? ""}`} e={e} direction="out" />
            ))}
            {incoming.slice(0, 20).map((e) => (
              <EdgeRow key={`in-${e.event_id}-${e.ts_start ?? ""}`} e={e} direction="in" />
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function EdgeRow({ e, direction }: { e: ScenarioEdge; direction: "out" | "in" }) {
  const hasErr = (e.status || "").startsWith("error");
  const arrow = direction === "out" ? "↗" : "↙";
  const peer =
    direction === "out"
      ? `${e.to_host || "?"} · ${e.to_session_id}`
      : `${e.from_host || "?"} · ${e.from_session_id}`;
  return (
    <div className="flex flex-col gap-0.5 px-2 py-1.5 rounded border border-border-soft">
      <div className="flex items-center gap-2">
        <span
          className="text-base"
          style={{
            color: hasErr
              ? "rgb(var(--role-error, 220 38 38))"
              : "rgb(var(--role-subagent))",
          }}
        >
          {arrow}
        </span>
        <span className="font-mono truncate">{peer}</span>
        {e.tool_name && (
          <span className="text-[10px] text-fg-muted font-mono">
            {e.tool_name}
          </span>
        )}
      </div>
      <div className="text-[10px] text-fg-muted tabular-nums flex gap-2">
        <span>{fmtLatency(e.latency_ms)}</span>
        {e.status && <span>· {e.status}</span>}
        {e.ts_start && <span className="truncate">· {e.ts_start.slice(11, 19)}Z</span>}
      </div>
    </div>
  );
}

function EdgeDetail({ edge }: { edge: ScenarioEdge }) {
  const hasErr = (edge.status || "").startsWith("error");
  const color = hasErr
    ? "rgb(var(--role-error, 220 38 38))"
    : "rgb(var(--role-subagent))";

  return (
    <>
      <header className="px-4 py-3 border-b border-border-soft">
        <div className="text-[10px] uppercase tracking-widest text-fg-muted">
          inter-agent call
        </div>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <span className="font-mono text-xs">{edge.from_session_id}</span>
          <span style={{ color }} className="text-base">
            →
          </span>
          <span className="font-mono text-xs">{edge.to_session_id}</span>
        </div>
        <div className="text-[10px] text-fg-muted tabular-nums mt-1">
          {edge.from_host || "?"} → {edge.to_host || "?"}
        </div>
      </header>

      <section className="px-4 py-3 border-b border-border-soft grid grid-cols-2 gap-y-2 gap-x-4 text-xs tabular-nums">
        <Stat label="Tool" value={edge.tool_name || "—"} mono />
        <Stat label="Status" value={edge.status || "—"} />
        <Stat label="Latency" value={fmtLatency(edge.latency_ms)} />
        <Stat label="Kind" value={edge.kind} />
      </section>

      <section className="px-4 py-3 border-b border-border-soft">
        <div className="text-[10px] uppercase tracking-widest text-fg-muted mb-1">
          Timestamps
        </div>
        <div className="font-mono text-[11px] leading-snug text-fg-primary">
          <div>
            <span className="text-fg-muted">start</span>{" "}
            {edge.ts_start || "(in-flight)"}
          </div>
          <div>
            <span className="text-fg-muted">done </span>{" "}
            {edge.ts_done || "(not yet)"}
          </div>
        </div>
      </section>

      <section className="px-4 py-3 border-b border-border-soft">
        <div className="text-[10px] uppercase tracking-widest text-fg-muted mb-1">
          Correlation
        </div>
        <div
          className="font-mono text-[11px] break-all text-fg-primary"
          title={edge.correlation_id}
        >
          {edge.correlation_id}
        </div>
      </section>

      <section className="px-4 py-3">
        <div className="text-[10px] uppercase tracking-widest text-fg-muted mb-1">
          Payload preview
        </div>
        <pre className="text-[11px] whitespace-pre-wrap break-words bg-bg-elevated rounded p-2 max-h-64 overflow-auto text-fg-primary">
          {edge.payload_preview || "(none)"}
        </pre>
      </section>
    </>
  );
}

function Stat({
  label,
  value,
  title,
  mono,
}: {
  label: string;
  value: string;
  title?: string;
  mono?: boolean;
}) {
  return (
    <div title={title}>
      <div className="text-[9px] uppercase tracking-widest text-fg-muted">
        {label}
      </div>
      <div
        className={`text-xs text-fg-primary ${mono ? "font-mono" : ""}`.trim()}
      >
        {value}
      </div>
    </div>
  );
}

export default function ScenarioDetailPanel({
  graph,
  selection,
  onClose,
  onOpenAgent,
}: Props) {
  if (!selection) {
    return (
      <aside className="w-80 shrink-0 border-l border-border-soft overflow-y-auto">
        <div className="px-4 py-3 text-[10px] uppercase tracking-widest text-fg-muted border-b border-border-soft">
          Details
        </div>
        <div className="p-4 text-xs text-fg-muted">
          Click a node rectangle, an agent, or an inter-agent edge to see its
          details here.
        </div>
      </aside>
    );
  }

  return (
    <aside className="w-80 shrink-0 border-l border-border-soft overflow-y-auto flex flex-col">
      <div className="sticky top-0 z-10 flex items-center justify-between px-4 py-2 border-b border-border-soft bg-canvas">
        <span className="text-[10px] uppercase tracking-widest text-fg-muted">
          Details
        </span>
        <button
          type="button"
          onClick={onClose}
          className="text-fg-muted hover:text-fg-primary text-sm leading-none"
          aria-label="Close detail panel"
        >
          ×
        </button>
      </div>
      {selection.kind === "host" ? (
        <HostDetail
          host={selection.host}
          graph={graph}
          onOpenAgent={onOpenAgent}
        />
      ) : (
        <EdgeDetail edge={selection.edge} />
      )}
    </aside>
  );
}
