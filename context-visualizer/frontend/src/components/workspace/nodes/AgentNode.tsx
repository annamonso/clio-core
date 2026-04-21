import { Handle, Position } from "reactflow";

export interface AgentNodeData {
  sessionId: string;
  role: string;
  label: string;
  callCount: number;
  tokens: number;
  costUsd: number;
  active: boolean;
  past: boolean;
}

function roleVar(role: string): string {
  switch (role) {
    case "orchestrator": return "--role-orchestrator";
    case "subagent":     return "--role-subagent";
    case "tool":         return "--role-tool";
    default:             return "--role-unknown";
  }
}

function formatK(n: number): string {
  if (!n) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export default function AgentNode({ data }: { data: AgentNodeData }) {
  const tokenVar = roleVar(data.role);
  return (
    <div
      className="rounded-lg border shadow-sm"
      style={{
        minWidth: 180,
        backgroundColor: "rgb(var(--bg-surface))",
        borderColor: data.active
          ? `rgb(var(${tokenVar}))`
          : "rgb(var(--border))",
        borderWidth: data.active ? 2 : 1,
        boxShadow: data.active
          ? `0 0 0 4px rgb(var(${tokenVar}) / 0.2)`
          : undefined,
        opacity: data.past || data.active ? 1 : 0.7,
        transition: "border-color 120ms, box-shadow 120ms, opacity 120ms",
      }}
    >
      <Handle type="target" position={Position.Left}  style={{ background: `rgb(var(${tokenVar}))`, border: 0 }} />
      <Handle type="source" position={Position.Right} style={{ background: `rgb(var(${tokenVar}))`, border: 0 }} />

      <div
        className="px-3 py-1.5 rounded-t-lg text-[11px] font-semibold uppercase tracking-wider flex items-center justify-between"
        style={{
          backgroundColor: `rgb(var(${tokenVar}) / 0.18)`,
          color: `rgb(var(${tokenVar}))`,
          borderBottom: `1px solid rgb(var(${tokenVar}) / 0.3)`,
        }}
      >
        <span>{data.role}</span>
        {data.active && (
          <span
            className="w-2 h-2 rounded-full animate-pulse-ring"
            style={{ backgroundColor: `rgb(var(${tokenVar}))` }}
          />
        )}
      </div>

      <div className="px-3 py-2 space-y-1">
        <div className="font-mono text-xs text-fg-primary truncate" title={data.sessionId}>
          {data.label}
        </div>
        <div className="flex items-center justify-between text-[10px] text-fg-muted tabular-nums">
          <span>{data.callCount} call{data.callCount === 1 ? "" : "s"}</span>
          <span>{formatK(data.tokens)} tok</span>
          {data.costUsd > 0 && (
            <span>${data.costUsd < 0.01 ? data.costUsd.toFixed(4) : data.costUsd.toFixed(2)}</span>
          )}
        </div>
      </div>
    </div>
  );
}
