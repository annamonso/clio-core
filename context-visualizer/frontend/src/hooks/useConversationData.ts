import { useEffect, useMemo, useState } from "react";
import { getAgentGraph, getConversationTurns } from "../api";
import type { AgentGraph, AgentNode, ConversationTurn } from "../types";

export interface NormalizedTurn {
  id: string;                  // interaction id
  sessionId: string;
  agentRole: string;           // "orchestrator" | "subagent" | "tool" | "unknown"
  turnNumber: number;
  turnType: string | null;
  provider: string;
  model: string | null;
  startTs: number;             // unix ms
  latencyMs: number;           // always >=0 (0 when unknown, for timeline rendering)
  hasLatency: boolean;
  parentInteractionId: string | null;
  responsePreview: string | null;
  toolCalls: Record<string, unknown>[];
  // Flat-fields surface from the backend adapter; used by the Workspace
  // error-toast-on-error-turn feature and by any future per-turn KPI
  // rendering. All optional because old interaction records may lack them.
  statusCode: number | null;
  error: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
  totalCostUsd: number | null;
  isError: boolean;
}

export interface ConversationData {
  conversationId: string;
  graph: AgentGraph | null;
  turns: NormalizedTurn[];
  lanes: string[];             // session ids in first-seen order (lane order)
  roleBySession: Map<string, string>;
  nodeBySession: Map<string, AgentNode>;
  totals: {
    agents: number;
    handoffs: number;
    calls: number;
    tokens: number;
    costUsd: number;
  };
  loading: boolean;
  error: string | null;
}

const EMPTY: ConversationData = {
  conversationId: "",
  graph: null,
  turns: [],
  lanes: [],
  roleBySession: new Map(),
  nodeBySession: new Map(),
  totals: { agents: 0, handoffs: 0, calls: 0, tokens: 0, costUsd: 0 },
  loading: false,
  error: null,
};

export function useConversationData(conversationId: string | null): ConversationData {
  const [graph, setGraph] = useState<AgentGraph | null>(null);
  const [rawTurns, setRawTurns] = useState<ConversationTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!conversationId) {
      setGraph(null);
      setRawTurns([]);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([
      getAgentGraph(conversationId).catch(() => null),
      getConversationTurns(conversationId).catch(() => [] as ConversationTurn[]),
    ])
      .then(([g, t]) => {
        if (cancelled) return;
        setGraph(g);
        setRawTurns(t);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e));
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [conversationId]);

  return useMemo<ConversationData>(() => {
    if (!conversationId) return EMPTY;

    const nodeBySession = new Map<string, AgentNode>();
    const roleBySession = new Map<string, string>();
    for (const n of graph?.nodes ?? []) {
      nodeBySession.set(n.session_id, n);
      roleBySession.set(n.session_id, n.agent_role ?? "unknown");
    }

    // Parse each timestamp up front so we can (a) sort by it safely even
    // when some are blank, and (b) fall back to a synthetic per-turn offset
    // when a legacy record has ``timestamp=""``. Without the fallback the
    // workspace timeline renders blank for pre-timestamp-fix records
    // because ``new Date("").getTime() === NaN`` collapses every bar to
    // width 0.
    const parsedTs: { src: ConversationTurn; parsed: number | null }[] = rawTurns.map((t) => {
      const p = new Date(t.timestamp).getTime();
      return { src: t, parsed: Number.isFinite(p) ? p : null };
    });
    parsedTs.sort((a, b) => {
      // Real timestamps first (in chronological order); blanks trailing
      // but stable relative to each other via turn_number so they still
      // render in a sensible order.
      const ap = a.parsed, bp = b.parsed;
      if (ap != null && bp != null) return ap - bp;
      if (ap != null) return -1;
      if (bp != null) return 1;
      return (a.src.turn_number ?? 0) - (b.src.turn_number ?? 0);
    });

    // Pick a base epoch for synthetic timestamps: first real ts we have,
    // else "now", so the synthetic range lands in a realistic window.
    const firstRealTs = parsedTs.find((p) => p.parsed != null)?.parsed ?? Date.now();
    const SYNTHETIC_STEP_MS = 1000;

    const turns: NormalizedTurn[] = parsedTs.map(({ src: t, parsed }, idx) => {
      const sessionId = t.session_id ?? "unknown";
      const role = roleBySession.get(sessionId) ?? "unknown";
      const ts = parsed ?? firstRealTs + idx * SYNTHETIC_STEP_MS;
      const hasLatency = t.total_latency_ms != null && !Number.isNaN(t.total_latency_ms);
      // Flat fields — emitted by the backend adapter since the live-feed port.
      // Old interaction records (pre-flat-fields backend) lack them, so each
      // read falls back to null and ``isError`` stays false.
      const statusCode = typeof t.status_code === "number" ? t.status_code : null;
      const error = typeof t.error === "string" && t.error ? t.error : null;
      const isError = (statusCode != null && statusCode >= 400) || error != null;
      return {
        id: t.id,
        sessionId,
        agentRole: role,
        turnNumber: t.turn_number,
        turnType: t.turn_type,
        provider: t.provider,
        model: t.model,
        startTs: ts,
        latencyMs: hasLatency ? Math.max(t.total_latency_ms!, 0) : 0,
        hasLatency,
        parentInteractionId: t.parent_interaction_id,
        responsePreview: t.response_text_preview,
        toolCalls: Array.isArray(t.tool_calls) ? t.tool_calls : [],
        statusCode,
        error,
        inputTokens: t.input_tokens ?? null,
        outputTokens: t.output_tokens ?? null,
        totalTokens: t.total_tokens ?? null,
        totalCostUsd: t.total_cost_usd ?? null,
        isError,
      };
    });

    // Lane order: by first appearance in turns (chronological).
    const lanes: string[] = [];
    const seen = new Set<string>();
    for (const t of turns) {
      if (!seen.has(t.sessionId)) {
        lanes.push(t.sessionId);
        seen.add(t.sessionId);
      }
    }

    const nodes = graph?.nodes ?? [];
    const totals = {
      agents: nodes.length,
      handoffs: graph?.edges?.length ?? 0,
      calls: nodes.reduce((s, n) => s + n.interaction_count, 0),
      tokens: nodes.reduce((s, n) => s + n.total_tokens, 0),
      costUsd: nodes.reduce((s, n) => s + n.total_cost_usd, 0),
    };

    return {
      conversationId,
      graph,
      turns,
      lanes,
      roleBySession,
      nodeBySession,
      totals,
      loading,
      error,
    };
  }, [conversationId, graph, rawTurns, loading, error]);
}
