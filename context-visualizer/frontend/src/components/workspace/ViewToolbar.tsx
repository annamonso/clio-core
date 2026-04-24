import type { AgentNode } from "../../types";

export type ViewMode = "sequential" | "aggregate";
export type Scope = "session" | "workflow";

interface Props {
  viewMode: ViewMode;
  onViewModeChange: (v: ViewMode) => void;
  scope: Scope;
  onScopeChange: (s: Scope) => void;
  lanes: string[];
  nodeBySession: Map<string, AgentNode>;
  selectedSessionId: string | null;
  onSelectedSessionChange: (id: string | null) => void;
}

function Pill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1 text-xs rounded-md transition-colors ${
        active
          ? "bg-accent text-white"
          : "bg-transparent text-fg-secondary hover:bg-elevate"
      }`}
    >
      {children}
    </button>
  );
}

function labelFor(
  sessionId: string,
  nodeBySession: Map<string, AgentNode>,
): string {
  const node = nodeBySession.get(sessionId);
  const role = node?.agent_role ?? "";
  const tail = sessionId.length > 20 ? "…" + sessionId.slice(-12) : sessionId;
  return role ? `${role}: ${tail}` : tail;
}

export default function ViewToolbar({
  viewMode,
  onViewModeChange,
  scope,
  onScopeChange,
  lanes,
  nodeBySession,
  selectedSessionId,
  onSelectedSessionChange,
}: Props) {
  return (
    <div className="px-4 py-2 border-b border-border-soft flex items-center gap-6 flex-wrap text-xs">
      <div className="flex items-center gap-2">
        <span className="uppercase tracking-wider text-fg-muted">View</span>
        <div className="inline-flex border border-border rounded-md p-0.5 bg-surface">
          <Pill
            active={viewMode === "sequential"}
            onClick={() => onViewModeChange("sequential")}
          >
            Sequential
          </Pill>
          <Pill
            active={viewMode === "aggregate"}
            onClick={() => onViewModeChange("aggregate")}
          >
            Aggregate
          </Pill>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span className="uppercase tracking-wider text-fg-muted">Scope</span>
        <div className="inline-flex border border-border rounded-md p-0.5 bg-surface">
          <Pill
            active={scope === "session"}
            onClick={() => onScopeChange("session")}
          >
            Selected session
          </Pill>
          <Pill
            active={scope === "workflow"}
            onClick={() => onScopeChange("workflow")}
          >
            Full workflow
          </Pill>
        </div>
        {scope === "session" && (
          <select
            value={selectedSessionId ?? ""}
            onChange={(e) => onSelectedSessionChange(e.target.value || null)}
            className="ml-2 px-2 py-1 text-xs rounded-md border border-border bg-surface text-fg-primary"
          >
            {lanes.length === 0 && <option value="">(no sessions)</option>}
            {lanes.map((s) => (
              <option key={s} value={s}>
                {labelFor(s, nodeBySession)}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}
