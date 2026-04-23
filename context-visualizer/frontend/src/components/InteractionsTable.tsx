import { useLiveInteractions } from "../hooks/useLiveInteractions";
import type { Provider } from "../types";

const PROVIDER_COLORS: Record<Provider, string> = {
  openai: "bg-emerald-900 text-emerald-300",
  anthropic: "bg-orange-900 text-orange-300",
  ollama: "bg-blue-900 text-blue-300",
  unknown: "bg-hover text-fg-primary",
};

function fmt(ms: number | null) {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function fmtTime(ts: string) {
  return new Date(ts).toLocaleTimeString();
}

interface Props {
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function LiveIndicator({ isLive }: { isLive: boolean }) {
  const dotClass = isLive
    ? "bg-[color:var(--ok)] animate-pulse"
    : "bg-[color:var(--warn)]";
  const label = isLive ? "Live" : "Polling";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-fg-secondary">
      <span className={`h-2 w-2 rounded-full ${dotClass}`} aria-hidden="true" />
      {label}
    </span>
  );
}

export default function InteractionsTable({ selectedId, onSelect }: Props) {
  const { rows, error, loading, isLive, refresh } = useLiveInteractions(100);

  if (loading) {
    return <div className="text-fg-secondary text-sm py-8 text-center">Loading…</div>;
  }
  if (error) {
    return (
      <div className="text-red-400 text-sm py-4">
        Error: {error}
        <button onClick={() => void refresh()} className="ml-3 underline">Retry</button>
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div>
        <div className="flex items-center justify-end mb-2">
          <LiveIndicator isLive={isLive} />
        </div>
        <div className="text-fg-secondary text-sm py-8 text-center">
          No interactions yet. Route LLM calls through the proxy to see them here.
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-end mb-2">
        <LiveIndicator isLive={isLive} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-border text-fg-secondary text-xs uppercase tracking-wider">
              <th className="text-left py-2 px-3 font-medium">Time</th>
              <th className="text-left py-2 px-3 font-medium">Provider</th>
              <th className="text-left py-2 px-3 font-medium">Model</th>
              <th className="text-left py-2 px-3 font-medium">Endpoint</th>
              <th className="text-center py-2 px-3 font-medium">Status</th>
              <th className="text-center py-2 px-3 font-medium">Stream</th>
              <th className="text-right py-2 px-3 font-medium">Latency</th>
              <th className="text-left py-2 px-3 font-medium">Preview</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isError = row.status_code != null && row.status_code >= 400;
              return (
                <tr
                  key={row.id}
                  onClick={() => onSelect(row.id)}
                  className={`border-b border-border/50 cursor-pointer transition-colors hover:bg-elevate/50 ${
                    selectedId === row.id ? "bg-surface" : ""
                  } ${isError ? "bg-red-950/30" : ""}`}
                >
                  <td className="py-2 px-3 font-mono text-xs text-fg-secondary whitespace-nowrap">
                    {fmtTime(row.timestamp)}
                  </td>
                  <td className="py-2 px-3">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${PROVIDER_COLORS[row.provider]}`}>
                      {row.provider}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-xs text-fg-primary max-w-[140px] truncate">
                    {row.model ?? <span className="text-fg-muted">—</span>}
                  </td>
                  <td className="py-2 px-3 font-mono text-xs text-fg-secondary">
                    <span className="text-fg-secondary">{row.method}</span> {row.path}
                  </td>
                  <td className="py-2 px-3 text-center">
                    <span
                      className={`text-xs font-mono ${
                        row.status_code == null
                          ? "text-fg-muted"
                          : row.status_code < 300
                          ? "text-green-400"
                          : row.status_code < 400
                          ? "text-yellow-400"
                          : "text-red-400"
                      }`}
                    >
                      {row.status_code ?? "—"}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-center text-fg-secondary text-xs">
                    {row.is_streaming ? "~" : ""}
                  </td>
                  <td className="py-2 px-3 text-right font-mono text-xs text-fg-secondary whitespace-nowrap">
                    {fmt(row.total_latency_ms)}
                  </td>
                  <td className="py-2 px-3 text-xs text-fg-secondary max-w-[220px] truncate">
                    {row.response_text_preview}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
