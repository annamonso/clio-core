import { useState } from "react";
import InteractionsTable from "../components/InteractionsTable";
import InteractionDrawer from "../components/InteractionDrawer";
import ErrorBoundary from "../components/ErrorBoundary";

/**
 * Live interactions feed ported from the reference project. The table polls
 * ``/_interceptor/interactions`` every 5 s (via ``useLiveInteractions``);
 * clicking a row opens a right-side drawer that renders the selected
 * interaction's Summary / Messages / Tools / Raw tabs.
 */
export default function InteractionsPage() {
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("iid");
  });

  const handleSelect = (id: string) => {
    setSelectedId(id);
    const params = new URLSearchParams(window.location.search);
    params.set("iid", id);
    const qs = params.toString();
    const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.replaceState(null, "", url);
  };

  const handleClose = () => {
    setSelectedId(null);
    const params = new URLSearchParams(window.location.search);
    params.delete("iid");
    const qs = params.toString();
    const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
    window.history.replaceState(null, "", url);
  };

  return (
    <div className="flex h-full min-h-0">
      <section className="flex-1 min-w-0 flex flex-col">
        <header className="px-4 py-2 border-b border-border-soft shrink-0">
          <span className="text-[10px] uppercase tracking-widest text-fg-muted">
            Live interactions
          </span>
          <div className="text-sm text-fg-primary mt-0.5">
            Every LLM call routed through the interceptor. Updates every few seconds.
          </div>
        </header>
        <div className="flex-1 overflow-auto px-4 py-3">
          <ErrorBoundary label="Interactions table">
            <InteractionsTable
              selectedId={selectedId}
              onSelect={handleSelect}
            />
          </ErrorBoundary>
        </div>
      </section>

      <ErrorBoundary label="Interaction drawer">
        <InteractionDrawer
          interactionId={selectedId}
          onClose={handleClose}
        />
      </ErrorBoundary>
    </div>
  );
}
