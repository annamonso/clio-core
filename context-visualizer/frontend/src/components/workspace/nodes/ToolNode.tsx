import { Handle, Position } from "reactflow";

export interface ToolNodeData {
  name: string;
  turnId: string;
}

const TOOL_VAR = "--role-tool";

export default function ToolNode({ data }: { data: ToolNodeData }) {
  return (
    <div
      className="rounded-md border shadow-sm"
      style={{
        minWidth: 120,
        backgroundColor: "rgb(var(--bg-surface))",
        borderColor: `rgb(var(${TOOL_VAR}))`,
        borderWidth: 1,
        boxShadow: `0 0 0 3px rgb(var(${TOOL_VAR}) / 0.18)`,
        opacity: 1,
        transition: "opacity 120ms",
      }}
    >
      <Handle type="target" position={Position.Left}  style={{ background: `rgb(var(${TOOL_VAR}))`, border: 0 }} />
      <Handle type="source" position={Position.Right} style={{ background: `rgb(var(${TOOL_VAR}))`, border: 0 }} />

      <div
        className="px-2 py-1 rounded-t-md text-[10px] font-semibold uppercase tracking-wider"
        style={{
          backgroundColor: `rgb(var(${TOOL_VAR}) / 0.18)`,
          color: `rgb(var(${TOOL_VAR}))`,
          borderBottom: `1px solid rgb(var(${TOOL_VAR}) / 0.3)`,
        }}
      >
        tool call
      </div>
      <div className="px-2 py-1.5">
        <div
          className="font-mono text-xs text-fg-primary truncate"
          title={data.name}
        >
          {data.name}
        </div>
      </div>
    </div>
  );
}
