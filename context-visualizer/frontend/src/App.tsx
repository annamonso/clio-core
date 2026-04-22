import { useState } from "react";
import WorkspacePage from "./pages/WorkspacePage";
import Toast, { type ToastState } from "./components/ui/Toast";
import ErrorBoundary from "./components/ErrorBoundary";

/**
 * Workspace shell. Intentionally trimmed vs. the upstream reference
 * (agent-interception's App.tsx): the raw-log modal, clear-interactions
 * button, and their dependencies (InteractionsTable, InteractionDrawer,
 * ClearModal) were not ported. This view is purely for multi-agent
 * conversation inspection; destructive interactions-log operations stay
 * out of the workspace UI.
 *
 * Theme: handled globally by the Flask base.html navbar. The SPA reads
 * the current palette from `data-theme` on <html>, which the base layout
 * sets before first paint. No per-SPA toggle needed — one source of
 * truth.
 */
export default function App() {
  const [toast, setToast] = useState<ToastState | null>(null);

  return (
    <div className="h-screen flex flex-col bg-canvas text-fg-primary">
      <header className="border-b border-border-soft px-4 py-2 flex items-center gap-3 shrink-0">
        <span className="text-base font-semibold tracking-tight">
          Clio Workspace
        </span>
        <span className="text-[10px] uppercase tracking-widest text-fg-muted">
          Multi-agent timeline
        </span>
      </header>

      <main className="flex-1 min-h-0">
        <ErrorBoundary label="Workspace">
          {/* onOpenRawLog is optional; the raw-log modal was not ported. */}
          <WorkspacePage />
        </ErrorBoundary>
      </main>

      <Toast toast={toast} onDismiss={() => setToast(null)} />
    </div>
  );
}
