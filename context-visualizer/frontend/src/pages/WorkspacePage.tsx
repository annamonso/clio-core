import { useEffect, useMemo, useState } from "react";
import ResizableSplit from "../components/workspace/ResizableSplit";
import ConversationHeader from "../components/workspace/ConversationHeader";
import ViewToolbar, { type Scope, type ViewMode } from "../components/workspace/ViewToolbar";
import AgentFlowGraph from "../components/workspace/AgentFlowGraph";
import TimelineView from "../components/workspace/TimelineView";
import DetailPanel from "../components/workspace/DetailPanel";
import ErrorBoundary from "../components/ErrorBoundary";
import Toast, { type ToastState } from "../components/ui/Toast";
import {
  useConversationData,
  type ConversationData,
  type NormalizedTurn,
} from "../hooks/useConversationData";
import { usePlayhead } from "../hooks/usePlayhead";

function errorToastMessage(turn: NormalizedTurn): string {
  const raw = turn.error ?? `HTTP ${turn.statusCode ?? "?"}`;
  const trimmed = raw.length > 160 ? raw.slice(0, 160) + "…" : raw;
  return `ERROR: ${trimmed}`;
}

interface Props {
  onOpenRawLog?: () => void;
}

export default function WorkspacePage({ onOpenRawLog }: Props) {
  const [conversationId, setConversationId] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("conv");
  });

  const [viewMode, setViewMode] = useState<ViewMode>("sequential");
  const [scope, setScope] = useState<Scope>("workflow");
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (conversationId) params.set("conv", conversationId);
    else params.delete("conv");
    const qs = params.toString();
    const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.replaceState(null, "", url);
  }, [conversationId]);

  const rawData = useConversationData(conversationId);

  // Auto-select the first lane when scope flips to "session" and nothing is picked yet,
  // or when the selected one disappears (conversation change).
  useEffect(() => {
    if (scope !== "session") return;
    if (selectedSessionId && rawData.lanes.includes(selectedSessionId)) return;
    setSelectedSessionId(rawData.lanes[0] ?? null);
  }, [scope, rawData.lanes, selectedSessionId]);

  // Scope filter: when "session", restrict turns/lanes to the chosen session.
  const data: ConversationData = useMemo(() => {
    if (scope !== "session" || !selectedSessionId) return rawData;
    const turns = rawData.turns.filter((t) => t.sessionId === selectedSessionId);
    const lanes = rawData.lanes.filter((s) => s === selectedSessionId);
    return { ...rawData, turns, lanes };
  }, [rawData, scope, selectedSessionId]);

  const playhead = usePlayhead(data.turns.length);
  const currentTurn = data.turns[playhead.idx] ?? null;

  // Error toast lives exactly as long as the playhead is on an error turn.
  // Moves to the next turn → toast disappears. Scrubs back → toast returns.
  // Ported from the reference project verbatim.
  const errorToast = useMemo<ToastState | null>(
    () =>
      currentTurn?.isError
        ? { type: "error", message: errorToastMessage(currentTurn) }
        : null,
    [currentTurn],
  );

  // Collapsible detail panel. Persist the choice so a full refresh preserves it.
  const [detailHidden, setDetailHidden] = useState<boolean>(() => {
    return window.localStorage.getItem("workspace.detail.hidden") === "1";
  });
  useEffect(() => {
    window.localStorage.setItem("workspace.detail.hidden", detailHidden ? "1" : "0");
  }, [detailHidden]);

  // Keyboard shortcuts.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === " ") { e.preventDefault(); playhead.toggle(); }
      else if (e.key === "ArrowLeft")  { e.preventDefault(); playhead.step(-1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); playhead.step( 1); }
      else if (e.key === "Home") { e.preventDefault(); playhead.setIdx(0); }
      else if (e.key === "End")  { e.preventDefault(); playhead.setIdx(data.turns.length - 1); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [playhead, data.turns.length]);

  const emptyHint = !conversationId
    ? "Select a conversation to begin."
    : data.loading
      ? "Loading conversation…"
      : data.error
        ? `Error: ${data.error}`
        : data.turns.length === 0
          ? "No interactions found for this conversation."
          : null;

  const graphAndDetail = detailHidden ? (
    <div className="relative h-full">
      <ErrorBoundary label="Agent graph">
        <AgentFlowGraph data={data} playhead={playhead} viewMode={viewMode} />
      </ErrorBoundary>
      <button
        type="button"
        onClick={() => setDetailHidden(false)}
        className="absolute top-2 right-2 z-10 text-xs px-2.5 py-1 rounded-md border border-border bg-surface/90 text-fg-secondary hover:text-fg-primary hover:bg-elevate shadow-sm backdrop-blur-sm"
        title="Show detail panel"
      >
        Show details
      </button>
    </div>
  ) : (
    <ResizableSplit
      direction="horizontal"
      initial={0.66}
      min={0.3}
      max={0.85}
      storageKey="workspace.split.horizontal"
      first={
        <ErrorBoundary label="Agent graph">
          <AgentFlowGraph data={data} playhead={playhead} viewMode={viewMode} />
        </ErrorBoundary>
      }
      second={
        <ErrorBoundary label="Detail panel">
          <DetailPanel
            turn={currentTurn}
            onClose={() => setDetailHidden(true)}
          />
        </ErrorBoundary>
      }
    />
  );

  return (
    <div className="flex flex-col h-full min-h-0">
      <ConversationHeader
        conversationId={conversationId}
        onConversationChange={setConversationId}
        totals={data.totals}
        onOpenRawLog={onOpenRawLog}
      />
      <ViewToolbar
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        scope={scope}
        onScopeChange={setScope}
        lanes={rawData.lanes}
        nodeBySession={rawData.nodeBySession}
        selectedSessionId={selectedSessionId}
        onSelectedSessionChange={setSelectedSessionId}
      />

      {emptyHint ? (
        <div className="flex-1 flex items-center justify-center text-fg-muted text-sm">
          {emptyHint}
        </div>
      ) : (
        <div className="flex-1 min-h-0">
          {viewMode === "aggregate" ? (
            graphAndDetail
          ) : (
            <ResizableSplit
              direction="vertical"
              initial={0.62}
              min={0.25}
              max={0.85}
              storageKey="workspace.split.vertical"
              first={graphAndDetail}
              second={
                <ErrorBoundary label="Timeline">
                  <TimelineView data={data} playhead={playhead} />
                </ErrorBoundary>
              }
            />
          )}
        </div>
      )}

      <Toast
        toast={errorToast}
        onDismiss={() => { /* controlled by playhead */ }}
        autoDismissMs={null}
        hideIcon
        hideClose
      />
    </div>
  );
}
