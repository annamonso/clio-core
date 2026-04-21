import { useEffect, useRef, useState } from "react";
import { getInteraction } from "../../api";
import type { Interaction } from "../../types";
import type { NormalizedTurn } from "../../hooks/useConversationData";
import SummaryTab from "../detail/SummaryTab";
import Messages from "../detail/Messages";
import ToolsTab from "../detail/ToolsTab";
import RawTab from "../detail/RawTab";
import ErrorBanner from "../detail/ErrorBanner";

const TABS = ["Summary", "Messages", "Tools", "Raw"] as const;
type Tab = typeof TABS[number];

interface Props {
  turn: NormalizedTurn | null;
}

const CACHE_LIMIT = 40;

function roleTokenVar(role: string): string {
  switch (role) {
    case "orchestrator": return "--role-orchestrator";
    case "subagent":     return "--role-subagent";
    case "tool":         return "--role-tool";
    default:             return "--role-unknown";
  }
}

export default function DetailPanel({ turn }: Props) {
  const [tab, setTab] = useState<Tab>("Summary");
  const [interaction, setInteraction] = useState<Interaction | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cacheRef = useRef<Map<string, Interaction>>(new Map());
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    if (!turn) {
      setInteraction(null);
      setError(null);
      setLoading(false);
      return;
    }
    const cached = cacheRef.current.get(turn.id);
    if (cached) {
      setInteraction(cached);
      setError(null);
      setLoading(false);
      return;
    }
    if (debounceRef.current != null) window.clearTimeout(debounceRef.current);
    setLoading(true);
    setError(null);
    const id = turn.id;
    debounceRef.current = window.setTimeout(() => {
      getInteraction(id)
        .then((data) => {
          cacheRef.current.set(id, data);
          // Cap cache size.
          if (cacheRef.current.size > CACHE_LIMIT) {
            const firstKey = cacheRef.current.keys().next().value;
            if (firstKey) cacheRef.current.delete(firstKey);
          }
          setInteraction(data);
          setLoading(false);
        })
        .catch((e) => {
          setError(String(e));
          setLoading(false);
        });
    }, 120);
    return () => {
      if (debounceRef.current != null) window.clearTimeout(debounceRef.current);
    };
  }, [turn]);

  if (!turn) {
    return (
      <div className="h-full flex items-center justify-center text-fg-muted text-sm bg-canvas">
        Select a turn to see details.
      </div>
    );
  }

  const roleVar = roleTokenVar(turn.agentRole);

  return (
    <div className="h-full flex flex-col bg-canvas border-l border-border-soft min-h-0">
      {/* Turn header */}
      <div
        className="px-4 py-3 border-b border-border-soft flex items-start gap-3"
        style={{ backgroundColor: `rgb(var(${roleVar}) / 0.08)` }}
      >
        <div
          className="w-1 self-stretch rounded"
          style={{ backgroundColor: `rgb(var(${roleVar}))` }}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider">
            <span style={{ color: `rgb(var(${roleVar}))` }} className="font-semibold">{turn.agentRole}</span>
            <span className="text-fg-muted">· turn {turn.turnNumber}</span>
            {turn.turnType && <span className="text-fg-muted">· {turn.turnType}</span>}
          </div>
          <div className="text-sm text-fg-primary truncate mt-0.5">
            {turn.model ?? "(unknown model)"} <span className="text-fg-muted">· {turn.provider}</span>
          </div>
          <div className="text-[11px] text-fg-muted font-mono mt-0.5 truncate" title={turn.sessionId}>
            session {turn.sessionId}
          </div>
        </div>
        <div className="text-right text-[11px] text-fg-muted tabular-nums shrink-0">
          {turn.hasLatency && <div>{turn.latencyMs.toFixed(0)}ms</div>}
          <div>{new Date(turn.startTs).toLocaleTimeString()}</div>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-border-soft overflow-x-auto shrink-0">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 text-xs whitespace-nowrap border-b-2 transition-colors ${
              tab === t
                ? "border-accent text-fg-primary"
                : "border-transparent text-fg-muted hover:text-fg-secondary"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4 min-h-0">
        {loading && <div className="text-fg-muted text-sm">Loading interaction…</div>}
        {error && <div className="text-error text-sm">Error: {error}</div>}
        {!loading && !error && interaction && (
          <>
            <ErrorBanner error={interaction.error} />
            {tab === "Summary"  && <SummaryTab interaction={interaction} />}
            {tab === "Messages" && <Messages   interaction={interaction} />}
            {tab === "Tools"    && <ToolsTab   interaction={interaction} />}
            {tab === "Raw"      && <RawTab     interaction={interaction} />}
          </>
        )}
      </div>
    </div>
  );
}
