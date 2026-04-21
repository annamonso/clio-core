import { useState } from "react";
import type { Interaction } from "../../types";
import JsonViewer from "../ui/JsonViewer";
import CopyButton from "../ui/CopyButton";

function HeadersTable({ headers }: { headers: Record<string, string> }) {
  const entries = Object.entries(headers);
  if (entries.length === 0) return <div className="text-fg-muted text-xs">No headers.</div>;
  return (
    <table className="w-full text-xs">
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k} className="border-b border-border-soft">
            <td className="py-1 pr-3 font-mono text-blue-300 align-top whitespace-nowrap w-1/3">{k}</td>
            <td className="py-1 font-mono text-fg-primary break-all">{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RequestPane({ interaction: i }: { interaction: Interaction }) {
  const [raw, setRaw] = useState(false);
  return (
    <div className="space-y-4">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-fg-secondary mb-2">Headers</div>
        <div className="bg-elevate rounded border border-border p-3">
          <HeadersTable headers={i.request_headers} />
        </div>
      </div>
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-fg-secondary">Body</div>
          <div className="flex gap-2 items-center">
            <button
              onClick={() => setRaw((v) => !v)}
              className="text-xs text-fg-secondary hover:text-fg-primary underline"
            >
              {raw ? "Parsed" : "Raw"}
            </button>
            <CopyButton text={raw ? (i.raw_request_body ?? "") : JSON.stringify(i.request_body, null, 2)} />
          </div>
        </div>
        {raw ? (
          <pre className="bg-elevate rounded border border-border p-3 text-xs font-mono text-fg-primary overflow-x-auto whitespace-pre-wrap">
            {i.raw_request_body ?? "(empty)"}
          </pre>
        ) : (
          i.request_body ? (
            <JsonViewer data={i.request_body} initiallyExpanded />
          ) : (
            <div className="text-fg-muted text-xs">No parsed body.</div>
          )
        )}
      </div>
    </div>
  );
}

export function ResponsePane({ interaction: i }: { interaction: Interaction }) {
  const [raw, setRaw] = useState(false);
  return (
    <div className="space-y-4">
      <div className="flex gap-3 text-xs">
        <span className={`font-mono font-semibold ${i.status_code && i.status_code < 300 ? "text-green-400" : "text-red-400"}`}>
          {i.status_code ?? "—"}
        </span>
      </div>
      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-fg-secondary mb-2">Headers</div>
        <div className="bg-elevate rounded border border-border p-3">
          <HeadersTable headers={i.response_headers} />
        </div>
      </div>
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-fg-secondary">Body</div>
          <div className="flex gap-2 items-center">
            <button
              onClick={() => setRaw((v) => !v)}
              className="text-xs text-fg-secondary hover:text-fg-primary underline"
            >
              {raw ? "Parsed" : "Raw"}
            </button>
            <CopyButton text={raw ? (i.raw_response_body ?? "") : JSON.stringify(i.response_body, null, 2)} />
          </div>
        </div>
        {raw ? (
          <pre className="bg-elevate rounded border border-border p-3 text-xs font-mono text-fg-primary overflow-x-auto whitespace-pre-wrap">
            {i.raw_response_body ?? "(empty)"}
          </pre>
        ) : (
          i.response_body ? (
            <JsonViewer data={i.response_body} initiallyExpanded />
          ) : (
            <div className="text-fg-muted text-xs">No parsed body.</div>
          )
        )}
      </div>
      {i.response_text && (
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-fg-secondary mb-2">Reconstructed text</div>
          <pre className="bg-elevate rounded border border-border p-3 text-xs text-fg-primary overflow-x-auto whitespace-pre-wrap">
            {i.response_text}
          </pre>
        </div>
      )}
      {i.tool_calls && i.tool_calls.length > 0 && (
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-fg-secondary mb-2">Tool calls</div>
          <JsonViewer data={i.tool_calls} initiallyExpanded />
        </div>
      )}
    </div>
  );
}

export default function RequestResponse({ interaction: i }: { interaction: Interaction }) {
  const [tab, setTab] = useState<"request" | "response">("request");

  return (
    <div>
      <div className="flex gap-1 border-b border-border mb-4">
        {(["request", "response"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm capitalize transition-colors border-b-2 -mb-px ${
              tab === t
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-fg-secondary hover:text-fg-primary"
            }`}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "request" ? (
        <RequestPane interaction={i} />
      ) : (
        <ResponsePane interaction={i} />
      )}
    </div>
  );
}
