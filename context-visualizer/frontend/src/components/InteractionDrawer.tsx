import { useEffect, useState } from "react";
import type { Interaction } from "../types";
import { getInteraction } from "../api";
import SummaryTab from "./detail/SummaryTab";
import Messages from "./detail/Messages";
import ToolsTab from "./detail/ToolsTab";
import RawTab from "./detail/RawTab";
import ErrorBanner from "./detail/ErrorBanner";

const TABS = ["Summary", "Messages", "Tools", "Raw"] as const;
type Tab = typeof TABS[number];

interface Props {
  interactionId: string | null;
  onClose: () => void;
}

/**
 * Right-side drawer that shows a single interaction's full detail using the
 * same SummaryTab / Messages / ToolsTab / RawTab components the conversation
 * DetailPanel uses. Kept separate from DetailPanel because that component
 * takes a ``NormalizedTurn`` derived from the playhead, while the
 * Interactions page works directly with ``Interaction`` from the REST
 * endpoint — no playhead, no normalisation step.
 */
export default function InteractionDrawer({ interactionId, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("Summary");
  const [interaction, setInteraction] = useState<Interaction | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!interactionId) {
      setInteraction(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getInteraction(interactionId)
      .then((data) => {
        if (cancelled) return;
        setInteraction(data);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [interactionId]);

  if (!interactionId) {
    return (
      <aside className="w-96 shrink-0 border-l border-border-soft flex items-center justify-center text-fg-muted text-sm bg-canvas">
        Click a row to see the full interaction.
      </aside>
    );
  }

  return (
    <aside className="w-96 shrink-0 border-l border-border-soft flex flex-col bg-canvas min-h-0">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border-soft flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-[11px] uppercase tracking-wider text-fg-muted">
            interaction
          </div>
          <div
            className="font-mono text-xs text-fg-primary truncate mt-0.5"
            title={interactionId}
          >
            {interactionId}
          </div>
          {interaction && (
            <div className="text-[11px] text-fg-muted font-mono mt-0.5 truncate">
              {interaction.method} {interaction.path}{" "}
              {interaction.status_code != null && (
                <span className="text-fg-secondary">
                  · {interaction.status_code}
                </span>
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="text-fg-muted hover:text-fg-primary text-sm leading-none px-1"
        >
          ×
        </button>
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
            {tab === "Summary" && <SummaryTab interaction={interaction} />}
            {tab === "Messages" && <Messages interaction={interaction} />}
            {tab === "Tools" && <ToolsTab interaction={interaction} />}
            {tab === "Raw" && <RawTab interaction={interaction} />}
          </>
        )}
      </div>
    </aside>
  );
}
