export function formatLatency(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms.toFixed(0)} ms`;
}

export function formatBytes(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n) || n <= 0) return "—";
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(2)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(2)} KB`;
  return `${n} B`;
}

export function formatTokens(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (n === 0) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toLocaleString();
}

export function formatCost(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n) || n <= 0) return "—";
  if (n < 0.0001) return `$${n.toExponential(2)}`;
  if (n < 0.01) return `$${n.toFixed(5)}`;
  if (n < 1) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

export function formatPct(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(n)) return "—";
  return `${n.toFixed(digits)}%`;
}

/**
 * Map an HTTP status code to a semantic tone used by StatusHero + badges.
 * null/0 maps to 'muted'; 2xx → ok; 3xx → warn; client errors that typically
 * surface as agent failures (401/403/429) → error; other 4xx → warn; 5xx → error.
 */
export type Tone = "ok" | "warn" | "error" | "muted";

export function statusTone(code: number | null | undefined): Tone {
  if (code == null || code === 0) return "muted";
  if (code >= 200 && code < 300) return "ok";
  if (code >= 300 && code < 400) return "warn";
  if (code === 401 || code === 403 || code === 429) return "error";
  if (code >= 400 && code < 500) return "warn";
  if (code >= 500) return "error";
  return "muted";
}

const STATUS_PHRASES: Record<number, string> = {
  200: "OK",
  201: "Created",
  204: "No content",
  301: "Moved permanently",
  302: "Found",
  304: "Not modified",
  400: "Bad request",
  401: "Unauthorized",
  403: "Forbidden",
  404: "Not found",
  408: "Request timeout",
  409: "Conflict",
  422: "Unprocessable entity",
  429: "Rate limit",
  500: "Internal server error",
  502: "Bad gateway",
  503: "Service unavailable",
  504: "Gateway timeout",
};

export function statusPhrase(code: number | null | undefined): string {
  if (code == null) return "no response";
  return STATUS_PHRASES[code] ?? (code >= 500 ? "server error" : code >= 400 ? "client error" : "response");
}
