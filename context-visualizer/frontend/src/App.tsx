import { useCallback, useEffect, useState } from "react";
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
 */
type Theme = "dark" | "light";

function getInitialTheme(): Theme {
  const attr = document.documentElement.dataset.theme;
  if (attr === "light" || attr === "dark") return attr;
  return "dark";
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [toast, setToast] = useState<ToastState | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("theme", theme);
    } catch {
      // Older browsers / privacy modes without storage: silently ignore.
    }
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((t) => (t === "light" ? "dark" : "light"));
  }, []);

  return (
    <div className="h-screen flex flex-col bg-canvas text-fg-primary">
      <header className="border-b border-border-soft px-4 py-2 flex items-center gap-3 shrink-0">
        <span className="text-base font-semibold tracking-tight">
          Clio Workspace
        </span>
        <span className="text-[10px] uppercase tracking-widest text-fg-muted">
          Multi-agent timeline
        </span>

        <div className="flex-1" />

        <button
          onClick={toggleTheme}
          className="p-1.5 rounded-md text-fg-muted hover:text-fg-primary hover:bg-elevate transition-colors"
          title={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
          aria-label="Toggle theme"
        >
          {theme === "light" ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <circle cx="12" cy="12" r="5" />
              <line x1="12" y1="1"  x2="12"   y2="3"    stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <line x1="12" y1="21" x2="12"   y2="23"   stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <line x1="4.22" y1="4.22"  x2="5.64"  y2="5.64"  stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <line x1="1" y1="12"  x2="3"  y2="12"  stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <line x1="21" y1="12" x2="23" y2="12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <line x1="4.22" y1="19.78" x2="5.64"  y2="18.36" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <line x1="18.36" y1="5.64"  x2="19.78" y2="4.22"  stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          )}
        </button>
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
