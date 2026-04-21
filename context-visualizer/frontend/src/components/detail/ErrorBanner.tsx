import { useState } from "react";
import { parseError } from "../../lib/parseError";
import CopyButton from "../ui/CopyButton";

interface Props {
  error: string | null | undefined;
}

const MAX_INLINE_MESSAGE = 480;

export default function ErrorBanner({ error }: Props) {
  const [showMore, setShowMore] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const parsed = parseError(error);
  if (!parsed) return null;

  const long = parsed.message.length > MAX_INLINE_MESSAGE;
  const displayedMessage = long && !showMore
    ? parsed.message.slice(0, MAX_INLINE_MESSAGE).trimEnd() + "…"
    : parsed.message;

  return (
    <div
      className="mb-4 rounded-lg border px-4 py-3 flex gap-3"
      style={{
        borderColor: "rgb(var(--error) / 0.4)",
        backgroundColor: "rgb(var(--error) / 0.08)",
      }}
    >
      <div
        className="mt-0.5 text-base leading-none shrink-0"
        style={{ color: "rgb(var(--error))" }}
        aria-hidden
      >⚠</div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-1">
          <span
            className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded"
            style={{
              color: "rgb(var(--error))",
              backgroundColor: "rgb(var(--error) / 0.15)",
              border: "1px solid rgb(var(--error) / 0.3)",
            }}
          >
            {parsed.type}
          </span>
          <span className="text-xs text-fg-muted">error</span>
        </div>
        <div className="text-sm text-fg-primary whitespace-pre-wrap break-words">
          {displayedMessage}
          {long && (
            <button
              onClick={() => setShowMore((v) => !v)}
              className="ml-2 text-xs text-accent hover:underline"
            >
              {showMore ? "show less" : "show more"}
            </button>
          )}
        </div>
        <div className="mt-2 flex items-center gap-2">
          <button
            onClick={() => setShowRaw((v) => !v)}
            className="text-[11px] text-fg-secondary hover:text-fg-primary underline underline-offset-2"
          >
            {showRaw ? "hide raw" : "raw"}
          </button>
          <CopyButton text={parsed.raw} />
        </div>
        {showRaw && (
          <pre className="mt-2 text-[11px] font-mono bg-surface border border-border-soft rounded p-2 max-h-48 overflow-auto whitespace-pre-wrap break-words">
            {parsed.raw}
          </pre>
        )}
      </div>
    </div>
  );
}
