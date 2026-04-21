import type { TokenUsage } from "../types";

/**
 * Per-1K-token USD price table, keyed by case-insensitive model-name prefix.
 * The longest-matching prefix wins so fine-grained variants (e.g. the
 * ``-20240620`` dated snapshot of claude-3-5-sonnet) resolve to the right
 * entry without every snapshot needing its own row.
 *
 * Prices are normalised to "per 1K tokens" to match the token units that
 * the UI displays. Ollama models are treated as free (self-hosted).
 *
 * This table is the single source of cost information for the workspace
 * view. The backend adapter does not fabricate cost estimates; the UI
 * computes them from ``token_usage`` via ``computeCost`` so prices can be
 * updated without a Python release.
 */
interface Rate {
  /** USD per 1,000 input tokens. */
  input: number;
  /** USD per 1,000 output tokens. */
  output: number;
}

const RATES: Array<{ prefix: string; rate: Rate }> = [
  // Anthropic (per-1K = per-million / 1000).
  { prefix: "claude-opus-4",       rate: { input: 0.015,   output: 0.075 } },
  { prefix: "claude-sonnet-4",     rate: { input: 0.003,   output: 0.015 } },
  { prefix: "claude-3-5-sonnet",   rate: { input: 0.003,   output: 0.015 } },
  { prefix: "claude-3-5-haiku",    rate: { input: 0.0008,  output: 0.004 } },
  { prefix: "claude-3-opus",       rate: { input: 0.015,   output: 0.075 } },
  { prefix: "claude-3-sonnet",     rate: { input: 0.003,   output: 0.015 } },
  { prefix: "claude-3-haiku",      rate: { input: 0.00025, output: 0.00125 } },

  // OpenAI.
  { prefix: "gpt-4o-mini",         rate: { input: 0.00015, output: 0.0006 } },
  { prefix: "gpt-4o",              rate: { input: 0.0025,  output: 0.01  } },
  { prefix: "gpt-4-turbo",         rate: { input: 0.01,    output: 0.03  } },
  { prefix: "gpt-4",               rate: { input: 0.03,    output: 0.06  } },
  { prefix: "gpt-3.5-turbo",       rate: { input: 0.0005,  output: 0.0015 } },
  { prefix: "o1-mini",             rate: { input: 0.003,   output: 0.012 } },
  { prefix: "o1",                  rate: { input: 0.015,   output: 0.06  } },
].sort((a, b) => b.prefix.length - a.prefix.length); // longest prefix first

/** Heuristic: self-hosted Ollama models are free. */
function isOllamaModel(model: string): boolean {
  const m = model.toLowerCase();
  return (
    m.startsWith("llama")
    || m.startsWith("mistral")
    || m.startsWith("mixtral")
    || m.startsWith("phi")
    || m.startsWith("qwen")
    || m.startsWith("gemma")
    || m.startsWith("ollama")
    || m.includes(":")                 // ollama tag notation, e.g. "llama3:70b"
  );
}

function rateFor(model: string): Rate | null {
  const key = model.toLowerCase();
  for (const { prefix, rate } of RATES) {
    if (key.startsWith(prefix.toLowerCase())) return rate;
  }
  return null;
}

/**
 * Compute USD cost for a single interaction from token usage and model name.
 *
 * Returns ``null`` for unknown models so UI callers can degrade to
 * ``—`` instead of showing a misleading zero. Returns ``0`` for
 * recognised free models (Ollama). ``input_tokens`` and
 * ``output_tokens`` default to 0 when absent so partial usage data
 * (e.g. streaming deltas) still produces something useful.
 */
export function computeCost(
  usage: TokenUsage | null | undefined,
  model: string | null | undefined,
): number | null {
  if (!model) return null;
  if (isOllamaModel(model)) return 0;

  const rate = rateFor(model);
  if (!rate) return null;

  const input = usage?.input_tokens ?? 0;
  const output = usage?.output_tokens ?? 0;
  if (input === 0 && output === 0) return null;

  return (input / 1000) * rate.input + (output / 1000) * rate.output;
}

/**
 * Aggregate cost across many interactions. Unknown-model interactions are
 * ignored rather than poisoning the total with ``NaN``; the aggregate falls
 * back to ``null`` only when *every* input was unknown.
 */
export function aggregateCost(
  items: Array<{ usage?: TokenUsage | null; model?: string | null }>,
): number | null {
  let total = 0;
  let anyKnown = false;
  for (const item of items) {
    const c = computeCost(item.usage ?? null, item.model ?? null);
    if (c == null) continue;
    total += c;
    anyKnown = true;
  }
  return anyKnown ? total : null;
}
