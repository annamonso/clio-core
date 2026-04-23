/**
 * Swim-lane style "host" group — renders a dashed, color-coded rectangle
 * that visually contains all agents co-resident on one physical node
 * (e.g. ares-comp-16). Agent nodes are rendered as children (ReactFlow
 * parent/child) so they sit inside the rectangle; inter-agent edges
 * cross between rectangles.
 */

export interface HostGroupData {
  host: string;
  /** 0–360 stable hue derived from the host name. */
  hue: number;
  agentCount: number;
  totalTokens: number;
  totalCostUsd: number;
  /** Number of outgoing inter-agent calls originating from this host. */
  outgoingCalls: number;
  /** Number of incoming inter-agent calls landing on this host. */
  incomingCalls: number;
}

function formatK(n: number): string {
  if (!n) return "0";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

export default function HostGroupNode({ data }: { data: HostGroupData }) {
  const { host, hue } = data;
  const label = host || "unknown host";
  return (
    <div
      className="host-group__frame"
      style={{
        width: "100%",
        height: "100%",
        border: `2px dashed hsl(${hue} 62% 48% / 0.75)`,
        borderRadius: 14,
        backgroundColor: `hsl(${hue} 62% 48% / 0.06)`,
        boxSizing: "border-box",
        cursor: "pointer",
        transition: "background-color 120ms",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 14px 4px 14px",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.02em",
          color: `hsl(${hue} 62% 34%)`,
          textTransform: "uppercase",
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            backgroundColor: `hsl(${hue} 62% 48%)`,
          }}
        />
        <span>node · {label}</span>
      </div>
      <div
        style={{
          padding: "0 14px 6px 14px",
          fontSize: 10,
          color: "rgb(var(--fg-muted))",
          fontVariantNumeric: "tabular-nums",
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <span>
          {data.agentCount} agent{data.agentCount === 1 ? "" : "s"}
        </span>
        <span>·</span>
        <span>{formatK(data.totalTokens)} tok</span>
        {data.totalCostUsd > 0 && (
          <>
            <span>·</span>
            <span>
              $
              {data.totalCostUsd < 0.01
                ? data.totalCostUsd.toFixed(4)
                : data.totalCostUsd.toFixed(2)}
            </span>
          </>
        )}
        {(data.outgoingCalls > 0 || data.incomingCalls > 0) && (
          <>
            <span>·</span>
            <span>
              {data.outgoingCalls}↗ {data.incomingCalls}↙
            </span>
          </>
        )}
      </div>
    </div>
  );
}
