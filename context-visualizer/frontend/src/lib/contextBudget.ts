/**
 * Split an interaction's input payload into three buckets so the UI can show
 * the user "where did my input tokens go":
 *
 *   • systemPrompt — the top-level system block the CLI injects (tool
 *     contracts, rules, model-of-the-world). Always pure scaffolding.
 *
 *   • reminder — text wrapped in <system-reminder>…</system-reminder> tags
 *     that the CLI injects as user messages (MCP instructions, skill
 *     manifests, auto-mode state, date). Scaffolding too.
 *
 *   • userPrompt — everything else in user messages. The actual thing you
 *     typed, or tool results coming back.
 *
 * Character counts are exact. Token counts are *estimates* pro-rated so the
 * sum equals the interaction's recorded ``input_tokens`` — accurate enough
 * to say "~95% of your bill is scaffolding" without tokenising locally.
 */

import type { Interaction } from "../types";

export interface ContextBudget {
  systemPromptChars: number;
  reminderChars: number;
  userPromptChars: number;

  /** Total input chars (system + reminder + userPrompt). */
  inputChars: number;

  /** Assistant output — kept separate; not part of input budget. */
  outputChars: number;

  /** Recorded token counts (may be null on streaming without usage). */
  inputTokens: number | null;
  outputTokens: number | null;

  /** Pro-rated token estimates; sum equals ``inputTokens`` when present. */
  systemPromptTokens: number;
  reminderTokens: number;
  userPromptTokens: number;

  /** Share of input that is CLI scaffolding, 0–100. */
  scaffoldingPct: number;
}

const REMINDER_RE = /<system-reminder>[\s\S]*?<\/system-reminder>/g;

function textFromContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    const parts: string[] = [];
    for (const b of content) {
      if (typeof b === "string") parts.push(b);
      else if (b && typeof b === "object") {
        const obj = b as Record<string, unknown>;
        if (obj.type === "text" && typeof obj.text === "string") {
          parts.push(obj.text);
        } else if (obj.type === "tool_result") {
          parts.push(textFromContent(obj.content));
        }
      }
    }
    return parts.join("\n");
  }
  return "";
}

function splitReminderFromUser(text: string): { reminder: number; user: number } {
  let reminderTotal = 0;
  const matches = text.match(REMINDER_RE) ?? [];
  for (const m of matches) reminderTotal += m.length;
  const userTotal = Math.max(0, text.length - reminderTotal);
  return { reminder: reminderTotal, user: userTotal };
}

export function computeContextBudget(i: Interaction): ContextBudget {
  const systemPromptChars = i.system_prompt?.length ?? 0;

  let reminderChars = 0;
  let userPromptChars = 0;

  for (const msg of i.messages ?? []) {
    const m = msg as Record<string, unknown>;
    if (m.role !== "user") continue;
    const text = textFromContent(m.content);
    const { reminder, user } = splitReminderFromUser(text);
    reminderChars += reminder;
    userPromptChars += user;
  }

  const outputChars = i.response_text?.length ?? 0;
  const inputChars = systemPromptChars + reminderChars + userPromptChars;

  const inputTokens = i.token_usage?.input_tokens ?? null;
  const outputTokens = i.token_usage?.output_tokens ?? null;

  // Pro-rate token estimate. If we don't know input_tokens, we just return 0s
  // for the estimates and let the UI fall back to showing chars.
  let systemPromptTokens = 0;
  let reminderTokens = 0;
  let userPromptTokens = 0;
  if (inputChars > 0 && inputTokens != null && inputTokens > 0) {
    const ratio = inputTokens / inputChars;
    systemPromptTokens = Math.round(systemPromptChars * ratio);
    reminderTokens = Math.round(reminderChars * ratio);
    // Make the sum match exactly to avoid the "388+0+2 ≠ 390" look.
    userPromptTokens = inputTokens - systemPromptTokens - reminderTokens;
    if (userPromptTokens < 0) userPromptTokens = 0;
  }

  const scaffoldingPct =
    inputChars > 0
      ? ((systemPromptChars + reminderChars) / inputChars) * 100
      : 0;

  return {
    systemPromptChars,
    reminderChars,
    userPromptChars,
    inputChars,
    outputChars,
    inputTokens,
    outputTokens,
    systemPromptTokens,
    reminderTokens,
    userPromptTokens,
    scaffoldingPct,
  };
}
