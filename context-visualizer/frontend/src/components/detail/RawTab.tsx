import { useState } from "react";
import type { Interaction } from "../../types";
import { RequestPane, ResponsePane } from "./RequestResponse";
import StreamTimeline from "./StreamTimeline";

type SubTab = "request" | "response" | "stream";

interface Props {
  interaction: Interaction;
}

export default function RawTab({ interaction: i }: Props) {
  const [sub, setSub] = useState<SubTab>("request");

  const subTabs: { key: SubTab; label: string; count?: number }[] = [
    { key: "request",  label: "Request" },
    { key: "response", label: "Response" },
    { key: "stream",   label: "Stream", count: i.stream_chunks.length },
  ];

  return (
    <div>
      <div className="flex gap-1 mb-4 border-b border-border-soft">
        {subTabs.map((t) => {
          const active = sub === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setSub(t.key)}
              className={`px-3 py-1.5 text-sm transition-colors border-b-2 -mb-px flex items-center gap-2 ${
                active
                  ? "border-accent text-fg-primary"
                  : "border-transparent text-fg-muted hover:text-fg-secondary"
              }`}
            >
              <span>{t.label}</span>
              {t.count != null && t.count > 0 && (
                <span className={`text-[10px] px-1.5 py-0.5 rounded tabular-nums ${
                  active ? "bg-accent/15 text-accent" : "bg-elevate text-fg-muted"
                }`}>
                  {t.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {sub === "request"  && <RequestPane interaction={i} />}
      {sub === "response" && <ResponsePane interaction={i} />}
      {sub === "stream"   && <StreamTimeline interaction={i} />}
    </div>
  );
}
