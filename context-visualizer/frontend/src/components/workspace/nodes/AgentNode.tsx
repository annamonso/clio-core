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
  aggregate?: boolean;
  toolBreakdown?: { name: string; count: number }[];
  host?: string;
  /** Optional scenario-level hue override (0–360). If unset, we fall back to
   *  the stable string hash — fine for the workspace view, which doesn't
   *  know about cross-host color coordination. */
  hostHueDeg?: number;
}

/** String-hash fallback for the Workspace view (no scenario-level context). */
function stableHostHue(host: string): number {
  let h = 0;
  for (let i = 0; i < host.length; i++) h = (h * 31 + host.charCodeAt(i)) | 0;
  // Multiply by Knuth's golden-ratio constant so strings that differ by
  // one char (ares-comp-16 vs -17) don't collide in adjacent hues.
  return Math.abs(Math.imul(h, 2654435761)) % 360;
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
        {data.host && (() => {
          const hue = data.hostHueDeg ?? stableHostHue(data.host);
          return (
            <div
              className="inline-flex items-center gap-1 text-[9px] font-mono px-1.5 py-0.5 rounded border"
              style={{
                borderColor: `hsl(${hue} 62% 48% / 0.55)`,
                color: `hsl(${hue} 62% 36%)`,
                backgroundColor: `hsl(${hue} 62% 48% / 0.1)`,
              }}
              title={`host: ${data.host}`}
            >
              <span className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: `hsl(${hue} 62% 48%)` }} />
              {data.host}
            </div>
          );
        })()}
        <div className="flex items-center justify-between text-[10px] text-fg-muted tabular-nums">
          <span>{data.callCount} call{data.callCount === 1 ? "" : "s"}</span>
          <span>{formatK(data.tokens)} tok</span>
          {data.costUsd > 0 && (
            <span>${data.costUsd < 0.01 ? data.costUsd.toFixed(4) : data.costUsd.toFixed(2)}</span>
          )}
        </div>
        {data.aggregate && data.toolBreakdown && data.toolBreakdown.length > 0 && (
          <div
            className="mt-1 pt-1.5 border-t border-border-soft flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] tabular-nums"
            style={{ color: `rgb(var(${tokenVar}))` }}
          >
            {data.toolBreakdown.slice(0, 4).map((t) => (
              <span key={t.name} title={`${t.name}: ${t.count}`}>
                {t.name}<span className="text-fg-muted"> ×{t.count}</span>
              </span>
            ))}
            {data.toolBreakdown.length > 4 && (
              <span className="text-fg-muted" title={data.toolBreakdown.slice(4).map((t) => `${t.name} ×${t.count}`).join(", ")}>
                +{data.toolBreakdown.length - 4} more
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
