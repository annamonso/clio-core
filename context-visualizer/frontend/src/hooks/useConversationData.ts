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

    const sorted = [...rawTurns].sort(
      (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
    );

    const turns: NormalizedTurn[] = sorted.map((t) => {
      const sessionId = t.session_id ?? "unknown";
      const role = roleBySession.get(sessionId) ?? "unknown";
      const ts = new Date(t.timestamp).getTime();
      const hasLatency = t.total_latency_ms != null && !Number.isNaN(t.total_latency_ms);
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
