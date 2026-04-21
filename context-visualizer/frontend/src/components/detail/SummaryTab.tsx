import { useState } from "react";
import type { Interaction } from "../../types";
import StatusHero from "./StatusHero";
import KpiCard from "./KpiCard";
import TokenBar from "./TokenBar";
import JsonViewer from "../ui/JsonViewer";
import { formatBytes, formatCost, formatLatency, formatTokens } from "../../lib/format";

interface Props {
  interaction: Interaction;
}

export default function SummaryTab({ interaction: i }: Props) {
  const [showRaw, setShowRaw] = useState(false);

  const tu = i.token_usage;
  const ce = i.cost_estimate;

  const totalTokens = tu?.total_tokens
    ?? (tu ? (tu.input_tokens ?? 0) + (tu.output_tokens ?? 0) + (tu.cache_read_tokens ?? 0) + (tu.cache_creation_tokens ?? 0) : 0);

  const reqBytes = i.raw_request_body?.length ?? 0;
  const resBytes = i.raw_response_body?.length ?? 0;

  const rawMetrics: Record<string, unknown> = {
    id: i.id,
    session_id: i.session_id,
    timestamp: i.timestamp,
    provider: i.provider,
    model: i.model,
    method: i.method,
    path: i.path,
    status_code: i.status_code,
    is_streaming: i.is_streaming,
    total_latency_ms: i.total_latency_ms,
    time_to_first_token_ms: i.time_to_first_token_ms,
    token_usage: i.token_usage,
    cost_estimate: i.cost_estimate,
    stream_chunk_count: i.stream_chunks.length,
    request_bytes: reqBytes || null,
    response_bytes: resBytes || null,
    tools_defined: i.tools?.length ?? 0,
    tool_calls_made: i.tool_calls?.length ?? 0,
    error: i.error,
  };

  const toolNames: string[] = (i.tool_calls ?? [])
    .map((c) => {
      const rec = c as Record<string, unknown>;
      return String(rec.name ?? rec.function ?? "");
    })
    .filter((n) => n.length > 0);

  return (
    <div className="space-y-4">
      <StatusHero
        statusCode={i.status_code}
        method={i.method}
        path={i.path}
        isStreaming={i.is_streaming}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <KpiCard
          title="Latency"
          headline={formatLatency(i.total_latency_ms)}
          sub={[
            { label: "Time to first token", value: formatLatency(i.time_to_first_token_ms) },
            { label: "Streaming",           value: i.is_streaming ? "yes" : "no",
              tone: i.is_streaming ? "default" : "muted" },
            { label: "Chunks",              value: i.stream_chunks.length ? String(i.stream_chunks.length) : "—" },
          ]}
        />

        <KpiCard title="Tokens" headline={totalTokens ? formatTokens(totalTokens) : "—"}>
          <TokenBar usage={tu} />
        </KpiCard>

        <KpiCard
          title="Cost"
          headline={formatCost(ce?.total_cost)}
          sub={
            ce
              ? [
                  { label: "Input",  value: formatCost(ce.input_cost) },
                  { label: "Output", value: formatCost(ce.output_cost) },
                  ...(ce.note ? [{ label: "Note", value: ce.note, tone: "muted" as const }] : []),
                ]
              : [{ label: "No billing info", value: "—", tone: "muted" }]
          }
        />

        <KpiCard
          title="Payload"
          sub={[
            { label: "Request",  value: formatBytes(reqBytes) },
            { label: "Response", value: formatBytes(resBytes) },
            { label: "Provider", value: i.provider },
            { label: "Model",    value: i.model ?? "—" },
          ]}
        />
      </div>

      {(i.tools?.length || i.tool_calls?.length) ? (
        <KpiCard
          title="Tools"
          sub={[
            { label: "Defined", value: String(i.tools?.length ?? 0) },
            { label: "Called",  value: String(i.tool_calls?.length ?? 0) },
          ]}
        >
          {toolNames.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {toolNames.map((n, idx) => (
                <span
                  key={`${n}-${idx}`}
                  className="text-[11px] font-mono px-2 py-0.5 rounded bg-elevate text-role-tool border border-border-soft"
                >
                  {n}
                </span>
              ))}
            </div>
          )}
        </KpiCard>
      ) : null}

      {i.image_metadata && i.image_metadata.count > 0 && (
        <KpiCard
          title="Images"
          headline={`${i.image_metadata.count} attached`}
          sub={[
            { label: "Types", value: i.image_metadata.media_types.join(", ") || "—" },
            ...(i.image_metadata.approximate_sizes.length > 0
              ? [{
                  label: "Approx sizes",
                  value: i.image_metadata.approximate_sizes.map((b) => formatBytes(b)).join(", "),
                }]
              : []),
          ]}
        />
      )}

      <div className="pt-2 border-t border-border-soft">
        <button
          onClick={() => setShowRaw((v) => !v)}
          className="text-xs text-fg-secondary hover:text-fg-primary underline underline-offset-2"
        >
          {showRaw ? "Hide raw metrics JSON" : "Show raw metrics JSON"}
        </button>
        {showRaw && (
          <div className="mt-2">
            <JsonViewer data={rawMetrics} initiallyExpanded />
          </div>
        )}
      </div>
    </div>
  );
}
