import { useEffect, useState } from "react";
import ResizableSplit from "../components/workspace/ResizableSplit";
import ConversationHeader from "../components/workspace/ConversationHeader";
import AgentFlowGraph from "../components/workspace/AgentFlowGraph";
import TimelineView from "../components/workspace/TimelineView";
import DetailPanel from "../components/workspace/DetailPanel";
import ErrorBoundary from "../components/ErrorBoundary";
import { useConversationData } from "../hooks/useConversationData";
import { usePlayhead } from "../hooks/usePlayhead";

interface Props {
  onOpenRawLog?: () => void;
}

export default function WorkspacePage({ onOpenRawLog }: Props) {
  const [conversationId, setConversationId] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("conv");
  });

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (conversationId) params.set("conv", conversationId);
    else params.delete("conv");
    const qs = params.toString();
    const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.replaceState(null, "", url);
  }, [conversationId]);

  const data = useConversationData(conversationId);
  const playhead = usePlayhead(data.turns.length);
  const currentTurn = data.turns[playhead.idx] ?? null;

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

  return (
    <div className="flex flex-col h-full min-h-0">
      <ConversationHeader
        conversationId={conversationId}
        onConversationChange={setConversationId}
        totals={data.totals}
        onOpenRawLog={onOpenRawLog}
      />

      {emptyHint ? (
        <div className="flex-1 flex items-center justify-center text-fg-muted text-sm">
          {emptyHint}
        </div>
      ) : (
        <div className="flex-1 min-h-0">
          <ResizableSplit
            direction="vertical"
            initial={0.62}
            min={0.25}
            max={0.85}
            storageKey="workspace.split.vertical"
            first={
              <ResizableSplit
                direction="horizontal"
                initial={0.66}
                min={0.3}
                max={0.85}
                storageKey="workspace.split.horizontal"
                first={
                  <ErrorBoundary label="Agent graph">
                    <AgentFlowGraph
                      data={data}
                      playhead={playhead}
                    />
                  </ErrorBoundary>
                }
                second={
                  <ErrorBoundary label="Detail panel">
                    <DetailPanel turn={currentTurn} />
                  </ErrorBoundary>
                }
              />
            }
            second={
              <ErrorBoundary label="Timeline">
                <TimelineView data={data} playhead={playhead} />
              </ErrorBoundary>
            }
          />
        </div>
      )}
    </div>
  );
}
