import { useState } from "react";
import type { Interaction, StreamChunk } from "../../types";
import ChunkSparkline from "./ChunkSparkline";
import { formatBytes, formatLatency } from "../../lib/format";

const PREVIEW_LEN = 120;

function chunkEventType(chunk: StreamChunk, provider: string): string {
  if (!chunk.parsed) return "raw";
  const p = chunk.parsed;
  if (provider === "anthropic" && p.type) return String(p.type);
  if (provider === "openai") {
    const choices = p.choices;
    if (Array.isArray(choices) && choices.length > 0) {
      const delta = (choices[0] as Record<string, unknown>).delta as Record<string, unknown> | undefined;
      if (delta?.tool_calls) return "tool_call_delta";
      if (delta?.content) return "content_delta";
    }
    if (p.usage) return "usage";
    return "chunk";
  }
  if (provider === "ollama" && p.done) return "done";
  return String(p.type ?? "chunk");
}

function fmtRelMs(first: number, current: number): string {
  const delta = current - first;
  return `+${delta.toFixed(0)}ms`;
}

function ChunkRow({ chunk, provider, firstMs }: { chunk: StreamChunk; provider: string; firstMs: number }) {
  const [expanded, setExpanded] = useState(false);
  const ts = new Date(chunk.timestamp).getTime();
  const preview = chunk.data.length > PREVIEW_LEN ? chunk.data.slice(0, PREVIEW_LEN) + "…" : chunk.data;
  const eventType = chunkEventType(chunk, provider);

  return (
    <div
      className="border-b border-border-soft hover:bg-surface/30 cursor-pointer"
      onClick={() => setExpanded((v) => !v)}
    >
      <div className="flex items-baseline gap-3 px-2 py-1.5 text-xs">
        <span className="text-fg-muted font-mono w-6 text-right shrink-0 select-none">
          {expanded ? "▾" : "▸"}{chunk.index}
        </span>
        <span className="text-fg-secondary font-mono whitespace-nowrap w-16 shrink-0">
          {isNaN(ts) ? "?" : fmtRelMs(firstMs, ts)}
        </span>
        <span className="text-accent font-mono whitespace-nowrap w-24 truncate shrink-0">{eventType}</span>
        <span className="text-fg-muted font-mono whitespace-nowrap w-16 shrink-0">{formatBytes(chunk.data.length)}</span>
        <span className="flex-1 min-w-0 truncate">
          {chunk.delta_text ? (
            <span className="text-role-subagent">{chunk.delta_text.slice(0, 60)}</span>
          ) : (
            <span className="text-fg-muted font-mono">{preview}</span>
          )}
        </span>
      </div>
      {expanded && (
        <pre className="mx-2 mb-2 p-2 bg-elevate rounded border border-border text-xs font-mono text-fg-primary overflow-x-auto whitespace-pre-wrap">
          {chunk.data}
        </pre>
      )}
    </div>
  );
}

export default function StreamTimeline({ interaction: i }: { interaction: Interaction }) {
  const chunks = i.stream_chunks;

  if (!i.is_streaming || chunks.length === 0) {
    return (
      <div className="text-fg-muted text-sm py-4">No stream chunks recorded.</div>
    );
  }

  const firstMs = new Date(chunks[0].timestamp).getTime();
  const lastMs = new Date(chunks[chunks.length - 1].timestamp).getTime();
  const streamDuration = isNaN(firstMs) || isNaN(lastMs) ? null : lastMs - firstMs;

  const reconstructed = i.response_text?.length ?? 0;

  return (
    <div>
      {/* Summary KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
        <Kpi label="Chunks" value={String(chunks.length)} />
        <Kpi label="TTFT"   value={formatLatency(i.time_to_first_token_ms)} />
        <Kpi label="Duration" value={formatLatency(streamDuration)} />
        <Kpi label="Reconstructed" value={reconstructed ? `${reconstructed.toLocaleString()} ch` : "—"} />
      </div>

      {/* Arrival-rate sparkline */}
      <div className="rounded border border-border-soft bg-surface p-3 mb-4">
        <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
          Arrival rate
        </div>
        <ChunkSparkline chunks={chunks} />
      </div>

      {/* Header */}
      <div className="flex gap-3 px-2 py-1 text-[10px] uppercase tracking-wider text-fg-muted border-b border-border font-medium">
        <span className="w-6 text-right shrink-0">#</span>
        <span className="w-16">Offset</span>
        <span className="w-24">Event</span>
        <span className="w-16">Size</span>
        <span className="flex-1">Delta / preview</span>
      </div>

      {/* Scrollable list */}
      <div className="overflow-y-auto max-h-[50vh]">
        {chunks.map((chunk) => (
          <ChunkRow
            key={chunk.index}
            chunk={chunk}
            provider={i.provider}
            firstMs={firstMs}
          />
        ))}
      </div>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border-soft bg-surface px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-fg-muted">{label}</div>
      <div className="text-sm font-semibold text-fg-primary tabular-nums">{value}</div>
    </div>
  );
}
