import { useMemo, useState } from "react";
import type { Interaction } from "../../types";
import JsonViewer from "../ui/JsonViewer";

interface ToolDef {
  name: string;
  description: string | null;
  schema: Record<string, unknown> | null;
  raw: Record<string, unknown>;
}

interface ToolCall {
  name: string;
  id: string | null;
  input: unknown;
  raw: Record<string, unknown>;
}

function extractDef(raw: Record<string, unknown>): ToolDef {
  const fn = raw.function as Record<string, unknown> | undefined;
  const name = String(raw.name ?? fn?.name ?? "(unnamed)");
  const description = raw.description
    ? String(raw.description)
    : fn?.description
      ? String(fn.description)
      : null;
  const schema =
    (raw.input_schema as Record<string, unknown> | undefined) ??
    (raw.parameters as Record<string, unknown> | undefined) ??
    (fn?.parameters as Record<string, unknown> | undefined) ??
    null;
  return { name, description, schema, raw };
}

function extractCall(raw: Record<string, unknown>): ToolCall {
  const fn = raw.function as Record<string, unknown> | undefined;
  const name = String(raw.name ?? fn?.name ?? "(unnamed)");
  const id = raw.id ? String(raw.id) : null;
  let input: unknown = raw.input ?? raw.arguments ?? fn?.arguments;
  if (typeof input === "string") {
    try { input = JSON.parse(input); } catch { /* keep as string */ }
  }
  return { name, id, input, raw };
}

export default function ToolsTab({ interaction }: { interaction: Interaction }) {
  const defs = useMemo(
    () => (Array.isArray(interaction.tools) ? interaction.tools.map((d) => extractDef(d as Record<string, unknown>)) : []),
    [interaction.tools],
  );
  const calls = useMemo(
    () => (Array.isArray(interaction.tool_calls) ? interaction.tool_calls.map((c) => extractCall(c as Record<string, unknown>)) : []),
    [interaction.tool_calls],
  );
  const defsByName = useMemo(() => {
    const m = new Map<string, ToolDef>();
    for (const d of defs) m.set(d.name, d);
    return m;
  }, [defs]);

  const [filter, setFilter] = useState("");
  const filteredDefs = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return defs;
    return defs.filter((d) => d.name.toLowerCase().includes(q) || (d.description ?? "").toLowerCase().includes(q));
  }, [defs, filter]);

  return (
    <div className="space-y-6">
      {/* Tool calls (the main event) */}
      <section>
        <h3 className="text-[10px] uppercase tracking-wider text-fg-muted mb-2">
          Tool calls emitted · {calls.length}
        </h3>
        {calls.length === 0 ? (
          <div className="text-xs text-fg-muted bg-surface border border-border-soft rounded-md p-3">
            No tool calls in this turn.
          </div>
        ) : (
          <div className="space-y-2">
            {calls.map((c, i) => (
              <ToolCallCard key={`${c.name}-${i}`} call={c} def={defsByName.get(c.name) ?? null} />
            ))}
          </div>
        )}
      </section>

      {/* Tool catalog */}
      <section>
        <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
          <h3 className="text-[10px] uppercase tracking-wider text-fg-muted">
            Tools available · {defs.length}
          </h3>
          {defs.length > 6 && (
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter…"
              className="text-xs px-2 py-1 rounded bg-surface border border-border-soft text-fg-primary placeholder:text-fg-muted outline-none focus:border-accent"
            />
          )}
        </div>

        {defs.length === 0 ? (
          <div className="text-xs text-fg-muted bg-surface border border-border-soft rounded-md p-3">
            No tools were provided to this turn.
          </div>
        ) : defs.length > 12 ? (
          <div className="flex flex-wrap gap-1.5">
            {filteredDefs.map((d, i) => (
              <ToolDefChip key={`${d.name}-${i}`} def={d} />
            ))}
          </div>
        ) : (
          <div className="space-y-1.5">
            {filteredDefs.map((d, i) => (
              <ToolDefRow key={`${d.name}-${i}`} def={d} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ToolCallCard({ call, def }: { call: ToolCall; def: ToolDef | null }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-md border border-border-soft bg-surface overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-elevate text-left transition-colors"
      >
        <span className="text-xs font-semibold font-mono text-role-tool">{call.name}</span>
        {call.id && (
          <span className="text-[10px] text-fg-muted font-mono truncate">#{call.id.slice(0, 8)}</span>
        )}
        {def?.description && !expanded && (
          <span className="text-[11px] text-fg-muted truncate italic min-w-0 flex-1">
            {def.description}
          </span>
        )}
        <span className="text-fg-muted text-xs ml-auto shrink-0">{expanded ? "▾" : "▸"}</span>
      </button>
      {expanded && (
        <div className="border-t border-border-soft p-3 space-y-3">
          {def?.description && (
            <p className="text-xs text-fg-secondary italic">{def.description}</p>
          )}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">Input</div>
            {call.input == null ? (
              <div className="text-xs text-fg-muted">(no input)</div>
            ) : typeof call.input === "string" ? (
              <pre className="text-[11px] font-mono bg-elevate border border-border-soft rounded p-2 whitespace-pre-wrap break-words">
                {call.input}
              </pre>
            ) : (
              <JsonViewer data={call.input as Record<string, unknown>} initiallyExpanded />
            )}
          </div>
          {def?.schema && (
            <details className="text-xs">
              <summary className="cursor-pointer text-fg-secondary hover:text-fg-primary">Declared schema</summary>
              <div className="mt-2"><JsonViewer data={def.schema} /></div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function ToolDefRow({ def }: { def: ToolDef }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded border border-border-soft bg-surface">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-start gap-2 px-3 py-1.5 hover:bg-elevate text-left transition-colors rounded"
      >
        <span className="text-xs font-mono font-semibold text-role-tool shrink-0">{def.name}</span>
        {def.description && (
          <span className="text-xs text-fg-muted italic truncate min-w-0 flex-1">
            {def.description}
          </span>
        )}
        <span className="text-fg-muted text-xs shrink-0">{expanded ? "▾" : "▸"}</span>
      </button>
      {expanded && def.schema && (
        <div className="border-t border-border-soft p-2">
          <JsonViewer data={def.schema} />
        </div>
      )}
    </div>
  );
}

function ToolDefChip({ def }: { def: ToolDef }) {
  return (
    <span
      title={def.description ?? ""}
      className="text-[11px] font-mono px-2 py-0.5 rounded bg-surface border border-border-soft text-fg-secondary"
    >
      {def.name}
    </span>
  );
}
