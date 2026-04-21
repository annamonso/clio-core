import { statusPhrase, statusTone } from "../../lib/format";

interface Props {
  statusCode: number | null | undefined;
  method: string;
  path: string;
  isStreaming: boolean;
}

function toneColors(tone: string): { bg: string; fg: string; border: string } {
  switch (tone) {
    case "ok":
      return { bg: "rgb(var(--ok) / 0.15)", fg: "rgb(var(--ok))", border: "rgb(var(--ok) / 0.4)" };
    case "warn":
      return { bg: "rgb(var(--warn) / 0.15)", fg: "rgb(var(--warn))", border: "rgb(var(--warn) / 0.4)" };
    case "error":
      return { bg: "rgb(var(--error) / 0.15)", fg: "rgb(var(--error))", border: "rgb(var(--error) / 0.4)" };
    default:
      return { bg: "rgb(var(--bg-elevate))", fg: "rgb(var(--fg-secondary))", border: "rgb(var(--border))" };
  }
}

export default function StatusHero({ statusCode, method, path, isStreaming }: Props) {
  const tone = statusTone(statusCode);
  const colors = toneColors(tone);
  const codeDisplay = statusCode == null ? "—" : String(statusCode);

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border-soft bg-surface px-4 py-3 mb-4 flex-wrap">
      <div
        className="flex items-baseline gap-2 px-3 py-1.5 rounded-md border shrink-0"
        style={{ backgroundColor: colors.bg, borderColor: colors.border }}
      >
        <span
          className="text-lg font-bold tabular-nums leading-none"
          style={{ color: colors.fg }}
        >
          {codeDisplay}
        </span>
        <span
          className="text-xs uppercase tracking-wider leading-none"
          style={{ color: colors.fg }}
        >
          {statusPhrase(statusCode)}
        </span>
      </div>

      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className="text-xs font-mono font-semibold text-fg-secondary px-1.5 py-0.5 rounded bg-elevate border border-border-soft">
          {method}
        </span>
        <span className="text-sm font-mono text-fg-primary truncate" title={path}>
          {path}
        </span>
      </div>

      {isStreaming && (
        <span
          className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full font-semibold shrink-0"
          style={{
            backgroundColor: "rgb(var(--accent) / 0.15)",
            color: "rgb(var(--accent))",
            border: "1px solid rgb(var(--accent) / 0.3)",
          }}
        >
          streaming
        </span>
      )}
    </div>
  );
}
