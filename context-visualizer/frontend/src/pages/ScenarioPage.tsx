import { useEffect, useMemo, useState } from "react";
import ScenarioFlowGraph from "../components/workspace/ScenarioFlowGraph";
import ScenarioList from "../components/workspace/ScenarioList";
import ScenarioDetailPanel, {
  type DetailSelection,
} from "../components/workspace/ScenarioDetailPanel";
import ErrorBoundary from "../components/ErrorBoundary";
import { getScenarioGraph } from "../api";
import type { ScenarioGraph } from "../types";

interface Props {
  /**
   * Called when the user clicks an agent node. Caller is responsible for
   * navigating to the Workspace tab with ``conv`` set to ``agentId`` (i.e. the
   * base session id). Keeping navigation in the parent means App.tsx owns
   * the tab state.
   */
  onOpenAgent?: (agentId: string) => void;
}

function useScenario(scenarioId: string | null) {
  const [graph, setGraph] = useState<ScenarioGraph | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!scenarioId) {
      setGraph(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getScenarioGraph(scenarioId)
      .then((g) => {
        if (!cancelled) setGraph(g);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [scenarioId]);

  return { graph, loading, error };
}

export default function ScenarioPage({ onOpenAgent }: Props) {
  const [scenarioId, setScenarioId] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("scenario");
  });

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (scenarioId) params.set("scenario", scenarioId);
    else params.delete("scenario");
    const qs = params.toString();
    const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.replaceState(null, "", url);
  }, [scenarioId]);

  const { graph, loading, error } = useScenario(scenarioId);

  // Detail-panel selection — reset when the loaded scenario changes.
  const [selection, setSelection] = useState<DetailSelection>(null);
  useEffect(() => {
    setSelection(null);
  }, [scenarioId]);

  const handleAgent = (agentId: string) => {
    onOpenAgent?.(agentId);
  };

  const handleHost = (host: string) => {
    setSelection({ kind: "host", host });
  };

  const handleEdgeSelect = (correlationId: string) => {
    if (!graph) return;
    const edge = graph.edges.find((e) => e.correlation_id === correlationId);
    if (edge) setSelection({ kind: "edge", edge });
  };

  const openAgentFromPanel = useMemo(
    () => (agentId: string) => {
      onOpenAgent?.(agentId);
    },
    [onOpenAgent],
  );

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-64 shrink-0 border-r border-border-soft overflow-y-auto">
        <div className="px-3 py-2 text-[10px] uppercase tracking-widest text-fg-muted border-b border-border-soft">
          Scenarios
        </div>
        <ScenarioList selected={scenarioId} onSelect={setScenarioId} />
      </aside>

      <section className="flex-1 min-w-0 flex flex-col">
        <header className="px-4 py-2 border-b border-border-soft flex items-center gap-3 shrink-0">
          <span className="font-mono text-sm truncate">
            {scenarioId ? (
              scenarioId
            ) : (
              <span className="text-fg-muted">No scenario selected</span>
            )}
          </span>
          {graph && (
            <span className="ml-auto text-[10px] text-fg-muted tabular-nums">
              {graph.agents.length} peer{graph.agents.length === 1 ? "" : "s"} ·{" "}
              {graph.edges.length} msg{graph.edges.length === 1 ? "" : "s"}
            </span>
          )}
        </header>

        <div className="flex-1 min-h-0">
          {!scenarioId && (
            <div className="h-full flex items-center justify-center text-fg-muted text-sm">
              Pick a scenario from the left to see the peer-agent graph.
            </div>
          )}
          {scenarioId && loading && (
            <div className="h-full flex items-center justify-center text-fg-muted text-sm">
              Loading scenario…
            </div>
          )}
          {scenarioId && error && (
            <div className="h-full flex items-center justify-center text-red-500 text-sm">
              Error: {error}
            </div>
          )}
          {scenarioId && !loading && !error && graph && (
            <ErrorBoundary label="Scenario graph">
              <ScenarioFlowGraph
                graph={graph}
                onAgentClick={handleAgent}
                onHostClick={handleHost}
                onEdgeSelect={handleEdgeSelect}
              />
            </ErrorBoundary>
          )}
        </div>
      </section>

      {graph && (
        <ScenarioDetailPanel
          graph={graph}
          selection={selection}
          onClose={() => setSelection(null)}
          onOpenAgent={openAgentFromPanel}
        />
      )}
    </div>
  );
}
