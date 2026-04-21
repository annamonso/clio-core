import { useEffect, useMemo, useRef, useState } from "react";
import { getConversations } from "../../api";
import type { ConversationSummary } from "../../types";

interface Totals {
  agents: number;
  handoffs: number;
  calls: number;
  tokens: number;
  costUsd: number;
}

interface Props {
  conversationId: string | null;
  onConversationChange: (id: string | null) => void;
  totals: Totals;
  onOpenRawLog?: () => void;
}

function formatTokens(n: number): string {
  if (!n) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

function formatCost(n: number): string {
  if (!n) return "—";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function Kpi({ icon, label, value, tint }: { icon: string; label: string; value: string; tint?: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-surface border border-border-soft min-w-[120px]">
      <span className={`text-base leading-none ${tint ?? "text-fg-muted"}`}>{icon}</span>
      <div className="flex flex-col leading-tight">
        <span className="text-[10px] uppercase tracking-wider text-fg-muted">{label}</span>
        <span className="text-sm font-semibold text-fg-primary tabular-nums">{value}</span>
      </div>
    </div>
  );
}

export default function ConversationHeader({
  conversationId,
  onConversationChange,
  totals,
  onOpenRawLog,
}: Props) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setLoading(true);
    getConversations()
      .then((cs) => setConversations(cs))
      .catch(() => setConversations([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [open]);

  const filtered = useMemo(() => {
    if (!query) return conversations;
    const q = query.toLowerCase();
    return conversations.filter((c) => c.conversationId.toLowerCase().includes(q));
  }, [conversations, query]);

  const selectedLabel = conversationId
    ? conversationId.slice(0, 8) + "…" + conversationId.slice(-4)
    : "Select conversation";

  return (
    <div className="px-4 py-3 border-b border-border-soft flex items-center gap-3 flex-wrap">
      {/* Conversation combobox */}
      <div ref={boxRef} className="relative">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-surface border border-border hover:bg-elevate text-sm text-fg-primary font-mono min-w-[220px]"
        >
          <span className="text-fg-muted text-xs">Conversation</span>
          <span className="flex-1 text-left truncate">{selectedLabel}</span>
          <svg width="12" height="12" viewBox="0 0 12 12" className="text-fg-muted">
            <path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
        {open && (
          <div className="absolute z-30 mt-1 w-[360px] max-h-[320px] overflow-hidden rounded-md border border-border bg-surface shadow-lg flex flex-col">
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search…"
              className="px-3 py-2 text-sm bg-transparent border-b border-border-soft text-fg-primary placeholder:text-fg-muted outline-none"
            />
            <div className="overflow-y-auto flex-1">
              {loading && <div className="px-3 py-2 text-xs text-fg-muted">Loading…</div>}
              {!loading && filtered.length === 0 && (
                <div className="px-3 py-4 text-xs text-fg-muted text-center">No conversations.</div>
              )}
              {filtered.map((c) => (
                <button
                  key={c.conversationId}
                  onClick={() => { onConversationChange(c.conversationId); setOpen(false); setQuery(""); }}
                  className={`w-full text-left px-3 py-2 text-xs hover:bg-elevate flex items-center justify-between gap-3 ${
                    c.conversationId === conversationId ? "bg-elevate" : ""
                  }`}
                >
                  <span className="font-mono text-fg-primary truncate">{c.conversationId}</span>
                  <span className="text-fg-muted shrink-0">{c.turnCount} turns</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* KPIs */}
      <div className="flex gap-2 flex-wrap">
        <Kpi icon="◈" label="Agents"   value={String(totals.agents)}   tint="text-role-orchestrator" />
        <Kpi icon="↻" label="Handoffs" value={String(totals.handoffs)} tint="text-role-subagent" />
        <Kpi icon="✎" label="LLM calls" value={String(totals.calls)}   tint="text-accent" />
        <Kpi icon="#" label="Tokens"   value={formatTokens(totals.tokens)} />
        <Kpi icon="$" label="Cost"     value={formatCost(totals.costUsd)} />
      </div>

      <div className="flex-1" />

      {onOpenRawLog && (
        <button
          onClick={onOpenRawLog}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border border-border text-fg-secondary hover:bg-elevate"
          title="View raw interaction log"
        >
          <span>☰</span> Raw log
        </button>
      )}
    </div>
  );
}
