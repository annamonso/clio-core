import { useState } from "react";
import CopyButton from "./CopyButton";

const TRUNCATE_LENGTH = 2000;

function colorize(json: string): string {
  return json
    .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g, (match) => {
      let cls = "text-yellow-300"; // number
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? "text-blue-300" : "text-green-300"; // key vs string
      } else if (/true|false/.test(match)) {
        cls = "text-purple-300";
      } else if (/null/.test(match)) {
        cls = "text-fg-secondary";
      }
      return `<span class="${cls}">${match}</span>`;
    });
}

interface JsonViewerProps {
  data: unknown;
  label?: string;
  initiallyExpanded?: boolean;
}

export default function JsonViewer({ data, label, initiallyExpanded = true }: JsonViewerProps) {
  const [expanded, setExpanded] = useState(initiallyExpanded);
  const [showAll, setShowAll] = useState(false);

  const raw = JSON.stringify(data, null, 2);
  const truncated = !showAll && raw.length > TRUNCATE_LENGTH;
  const displayed = truncated ? raw.slice(0, TRUNCATE_LENGTH) + "\n..." : raw;
  const highlighted = colorize(displayed.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"));

  return (
    <div className="rounded border border-border bg-elevate overflow-hidden">
      {label && (
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-surface">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-xs font-medium text-fg-primary hover:text-white"
          >
            {expanded ? "▾" : "▸"} {label}
          </button>
          <CopyButton text={raw} />
        </div>
      )}
      {expanded && (
        <div className="relative">
          {!label && (
            <div className="absolute top-2 right-2">
              <CopyButton text={raw} />
            </div>
          )}
          <pre
            className="text-xs p-3 overflow-x-auto font-mono text-fg-primary leading-relaxed"
            dangerouslySetInnerHTML={{ __html: highlighted }}
          />
          {truncated && (
            <div className="px-3 pb-2">
              <button
                onClick={() => setShowAll(true)}
                className="text-xs text-blue-400 hover:underline"
              >
                Show all ({raw.length.toLocaleString()} chars)
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
