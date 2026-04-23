import { useState } from "react";
import type { Interaction } from "../../types";

const ROLE_STYLES: Record<string, string> = {
  system: "bg-purple-900/50 text-purple-300 border-purple-700",
  user: "bg-blue-900/30 text-blue-300 border-blue-800",
  assistant: "bg-emerald-900/30 text-emerald-300 border-emerald-800",
  tool: "bg-orange-900/30 text-orange-300 border-orange-800",
};

function RoleBadge({ role }: { role: string }) {
  const cls = ROLE_STYLES[role] ?? "bg-surface text-fg-secondary border-border";
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${cls}`}>
      {role}
    </span>
  );
}

function ReminderBlock({ body }: { body: string }) {
  const [open, setOpen] = useState(false);
  const preview =
    body.slice(0, 140).replace(/\s+/g, " ").trim() +
    (body.length > 140 ? "…" : "");
  return (
    <div className="my-1 rounded border border-border-soft bg-surface/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2 py-1.5 text-left hover:bg-elevate/40 transition-colors"
      >
        <span
          className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded"
          style={{
            color: "rgb(var(--role-unknown))",
            backgroundColor: "rgb(var(--role-unknown) / 0.12)",
            border: "1px solid rgb(var(--role-unknown) / 0.3)",
          }}
          title="CLI-injected runtime context — not user-authored"
        >
          CLI scaffolding
        </span>
        <span className="text-[11px] text-fg-muted tabular-nums">
          {body.length.toLocaleString()} chars
        </span>
        <span className="flex-1 truncate text-[11px] text-fg-muted italic">
          {open ? "" : preview}
        </span>
        <span className="text-fg-muted text-xs shrink-0">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <pre className="px-2 pb-2 text-xs text-fg-secondary whitespace-pre-wrap font-mono">
          {body}
        </pre>
      )}
    </div>
  );
}

/** Splits a plain-text blob on <system-reminder>…</system-reminder> markers
 *  so the renderer can dim the scaffolding and leave the real user text full-opacity. */
function renderTextWithReminders(text: string, keyPrefix: string) {
  const chunks: { kind: "text" | "reminder"; body: string; key: string }[] = [];
  const re = /<system-reminder>([\s\S]*?)<\/system-reminder>/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      const body = text.slice(last, m.index);
      if (body.trim()) chunks.push({ kind: "text", body, key: `${keyPrefix}-t${i++}` });
    }
    chunks.push({ kind: "reminder", body: m[1], key: `${keyPrefix}-r${i++}` });
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    const body = text.slice(last);
    if (body.trim()) chunks.push({ kind: "text", body, key: `${keyPrefix}-t${i++}` });
  }
  return chunks;
}

function ContentBlock({ content }: { content: unknown }) {
  if (content == null) return null;
  if (typeof content === "string") {
    // Pull out <system-reminder> blocks first — they dominate the visual field
    // when the CLI injects MCP instructions / skill manifests into user messages.
    if (content.includes("<system-reminder>")) {
      const chunks = renderTextWithReminders(content, "cb");
      return (
        <div className="space-y-1">
          {chunks.map((c) =>
            c.kind === "reminder" ? (
              <ReminderBlock key={c.key} body={c.body} />
            ) : (
              <ContentBlock key={c.key} content={c.body} />
            ),
          )}
        </div>
      );
    }
    // Detect code fences
    if (content.includes("```")) {
      const parts = content.split(/(```[\s\S]*?```)/g);
      return (
        <div className="text-sm text-fg-primary whitespace-pre-wrap space-y-1">
          {parts.map((part, i) =>
            part.startsWith("```") ? (
              <pre key={i} className="bg-elevate rounded p-2 text-xs font-mono overflow-x-auto border border-border">
                {part.replace(/^```\w*\n?/, "").replace(/```$/, "")}
              </pre>
            ) : (
              <span key={i}>{part}</span>
            )
          )}
        </div>
      );
    }
    return <p className="text-sm text-fg-primary whitespace-pre-wrap">{content}</p>;
  }
  if (Array.isArray(content)) {
    return (
      <div className="space-y-1">
        {content.map((block, i) => {
          if (typeof block === "string") return <ContentBlock key={i} content={block} />;
          if (block && typeof block === "object") {
            const b = block as Record<string, unknown>;
            if (b.type === "text") return <ContentBlock key={i} content={b.text} />;
            if (b.type === "image") {
              return (
                <div key={i} className="text-xs text-fg-secondary italic bg-surface rounded px-2 py-1 border border-border">
                  [Image: {String(b.media_type ?? "unknown")}, ~{String(b.approximate_size ?? "?")} bytes]
                </div>
              );
            }
            if (b.type === "tool_use") {
              return (
                <div key={i} className="rounded border border-orange-700/50 bg-orange-900/20 p-2 text-xs">
                  <div className="font-semibold text-orange-300 mb-1">Tool: {String(b.name)}</div>
                  <pre className="font-mono text-orange-200/80 text-xs overflow-x-auto whitespace-pre-wrap">
                    {JSON.stringify(b.input, null, 2)}
                  </pre>
                </div>
              );
            }
            if (b.type === "tool_result") {
              return (
                <div key={i} className="rounded border border-yellow-700/50 bg-yellow-900/20 p-2 text-xs">
                  <div className="font-semibold text-yellow-300 mb-1">Tool result (id: {String(b.tool_use_id)})</div>
                  <ContentBlock content={b.content} />
                </div>
              );
            }
            if (b.type === "thinking") {
              return (
                <div key={i} className="rounded border border-border bg-surface/50 p-2 text-xs text-fg-secondary italic">
                  [thinking]: {String(b.thinking ?? "")}
                </div>
              );
            }
          }
          return (
            <pre key={i} className="text-xs font-mono text-fg-secondary overflow-x-auto">
              {JSON.stringify(block, null, 2)}
            </pre>
          );
        })}
      </div>
    );
  }
  return (
    <pre className="text-xs font-mono text-fg-secondary overflow-x-auto whitespace-pre-wrap">
      {JSON.stringify(content, null, 2)}
    </pre>
  );
}

interface MessageBubble {
  role: string;
  content: unknown;
  name?: string;
}

function Bubble({ msg }: { msg: MessageBubble }) {
  return (
    <div className="flex gap-3 py-2 border-b border-border/50">
      <div className="pt-0.5 shrink-0">
        <RoleBadge role={msg.role} />
      </div>
      <div className="flex-1 min-w-0">
        {msg.name && (
          <div className="text-xs text-fg-secondary mb-1">name: {msg.name}</div>
        )}
        <ContentBlock content={msg.content} />
      </div>
    </div>
  );
}

const LONG_SYSTEM_PROMPT_THRESHOLD = 500;

function SystemPromptCard({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  const preview = content.slice(0, 180).trim() + (content.length > 180 ? "…" : "");
  return (
    <div className="mb-3 rounded-lg border border-border-soft bg-surface">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-elevate transition-colors rounded-lg"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded"
            style={{
              color: "rgb(var(--role-tool))",
              backgroundColor: "rgb(var(--role-tool) / 0.15)",
              border: "1px solid rgb(var(--role-tool) / 0.3)",
            }}
          >
            System prompt
          </span>
          <span className="text-xs text-fg-muted tabular-nums">
            {content.length.toLocaleString()} chars
          </span>
        </div>
        <span className="text-fg-muted text-xs shrink-0">{open ? "▾" : "▸"}</span>
      </button>
      {!open && (
        <div className="px-3 pb-2 text-xs text-fg-muted italic line-clamp-2">
          {preview}
        </div>
      )}
      {open && (
        <div className="px-3 pb-3 border-t border-border-soft pt-3">
          <ContentBlock content={content} />
        </div>
      )}
    </div>
  );
}

export default function Messages({ interaction: i }: { interaction: Interaction }) {
  const messages: MessageBubble[] = [];

  // System prompt: handled separately if long.
  const longSystem = i.system_prompt && i.system_prompt.length > LONG_SYSTEM_PROMPT_THRESHOLD
    ? i.system_prompt
    : null;
  if (i.system_prompt && !longSystem) {
    messages.push({ role: "system", content: i.system_prompt });
  }

  if (i.messages) {
    for (const msg of i.messages) {
      const m = msg as Record<string, unknown>;
      messages.push({
        role: String(m.role ?? "unknown"),
        content: m.content,
        name: m.name ? String(m.name) : undefined,
      });
    }
  }

  // Assistant response
  if (i.response_text || (i.tool_calls && i.tool_calls.length > 0)) {
    const assistantContent: unknown[] = [];
    if (i.response_text) assistantContent.push(i.response_text);
    if (i.tool_calls) {
      for (const tc of i.tool_calls) {
        assistantContent.push(tc);
      }
    }
    messages.push({ role: "assistant", content: assistantContent.length === 1 ? assistantContent[0] : assistantContent });
  }

  if (messages.length === 0 && !longSystem) {
    return <div className="text-fg-muted text-sm py-4">No messages available.</div>;
  }

  return (
    <div>
      {longSystem && <SystemPromptCard content={longSystem} />}
      {messages.length > 0 && (
        <>
          <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-2">
            {messages.length} message{messages.length === 1 ? "" : "s"}
          </div>
          <div className="space-y-0">
            {messages.map((msg, idx) => (
              <Bubble key={idx} msg={msg} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
