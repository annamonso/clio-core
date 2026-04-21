export interface ParsedError {
  type: string;
  message: string;
  raw: string;
}

/**
 * Best-effort parser for error strings stored in Interaction.error.
 * Tries provider-specific JSON envelopes (Anthropic / OpenAI), then
 * "type: message" colon-prefix, then falls back to the raw string.
 */
export function parseError(raw: string | null | undefined): ParsedError | null {
  if (!raw) return null;
  const trimmed = raw.trim();

  // Try JSON parse.
  try {
    const obj = JSON.parse(trimmed);
    const parsed = extractFromJson(obj);
    if (parsed) return { ...parsed, raw: trimmed };
  } catch {
    // Not JSON — continue.
  }

  // Try "type: message" colon split.
  const colonIdx = trimmed.indexOf(":");
  if (colonIdx > 0 && colonIdx < 64) {
    const potentialType = trimmed.slice(0, colonIdx).trim();
    const rest = trimmed.slice(colonIdx + 1).trim();
    if (isErrorTypeLike(potentialType) && rest.length > 0) {
      return { type: potentialType, message: rest, raw: trimmed };
    }
  }

  return { type: "error", message: trimmed, raw: trimmed };
}

function isErrorTypeLike(s: string): boolean {
  return /^[a-z][a-z0-9_]*$/i.test(s) && s.length <= 48;
}

function extractFromJson(obj: unknown): { type: string; message: string } | null {
  if (!obj || typeof obj !== "object") return null;
  const rec = obj as Record<string, unknown>;

  // Anthropic: { type: "error", error: { type, message } }
  const nested = rec.error;
  if (nested && typeof nested === "object") {
    const inner = nested as Record<string, unknown>;
    const type = strOrNull(inner.type) ?? strOrNull(rec.type) ?? "error";
    const message = strOrNull(inner.message) ?? strOrNull(inner.msg) ?? strOrNull(nested);
    if (message) return { type, message };
  }

  // OpenAI sometimes: { message, type, code }
  const topMessage = strOrNull(rec.message) ?? strOrNull(rec.detail) ?? strOrNull(rec.error);
  const topType = strOrNull(rec.type) ?? strOrNull(rec.code) ?? "error";
  if (topMessage) return { type: topType, message: topMessage };

  return null;
}

function strOrNull(v: unknown): string | null {
  if (typeof v === "string" && v.trim().length > 0) return v;
  return null;
}
