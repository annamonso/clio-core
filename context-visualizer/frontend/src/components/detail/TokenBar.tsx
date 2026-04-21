import { formatTokens } from "../../lib/format";
import type { TokenUsage } from "../../types";

interface Segment {
  label: string;
  value: number;
  color: string;
}

interface Props {
  usage: TokenUsage | null;
}

export default function TokenBar({ usage }: Props) {
  if (!usage) {
    return <div className="text-xs text-fg-muted">No token usage reported.</div>;
  }

  const segments: Segment[] = [
    { label: "input",         value: usage.input_tokens ?? 0,          color: "rgb(var(--accent))" },
    { label: "cache read",    value: usage.cache_read_tokens ?? 0,     color: "rgb(var(--accent-muted))" },
    { label: "cache create",  value: usage.cache_creation_tokens ?? 0, color: "rgb(var(--warn))" },
    { label: "output",        value: usage.output_tokens ?? 0,         color: "rgb(var(--role-subagent))" },
  ].filter((s) => s.value > 0);

  const total = segments.reduce((s, x) => s + x.value, 0);

  if (total === 0) {
    return <div className="text-xs text-fg-muted">No token usage reported.</div>;
  }

  const cacheRead = usage.cache_read_tokens ?? 0;
  const input = usage.input_tokens ?? 0;
  const cacheHitPct = (input + cacheRead) > 0
    ? Math.round((cacheRead / (input + cacheRead)) * 100)
    : null;

  return (
    <div>
      <div
        className="flex h-2.5 w-full overflow-hidden rounded-full bg-elevate"
        role="img"
        aria-label="Token breakdown"
      >
        {segments.map((seg) => (
          <div
            key={seg.label}
            title={`${seg.label}: ${formatTokens(seg.value)} (${((seg.value / total) * 100).toFixed(1)}%)`}
            style={{
              width: `${(seg.value / total) * 100}%`,
              backgroundColor: seg.color,
            }}
          />
        ))}
      </div>

      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
        {segments.map((seg) => (
          <div key={seg.label} className="flex items-center gap-1.5 text-xs min-w-0">
            <span
              className="w-2 h-2 rounded-sm shrink-0"
              style={{ backgroundColor: seg.color }}
            />
            <span className="text-fg-muted truncate">{seg.label}</span>
            <span className="text-fg-secondary tabular-nums ml-auto">{formatTokens(seg.value)}</span>
          </div>
        ))}
      </div>

      {cacheHitPct !== null && cacheRead > 0 && (
        <div className="mt-2 inline-flex items-center gap-1 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded"
          style={{
            backgroundColor: "rgb(var(--accent-muted) / 0.2)",
            color: "rgb(var(--accent))",
          }}
        >
          {cacheHitPct}% cache hit
        </div>
      )}
    </div>
  );
}
