import type { AgentGraph, ClearScope, ConversationSummary, ConversationTurn, Interaction, InteractionSummary, SessionGraph, SessionInfo, ToolCallStep } from "./types";

interface ListParams {
  limit?: number;
  offset?: number;
  provider?: string;
  model?: string;
  session_id?: string;
}

export async function listInteractions(
  params: ListParams = {}
): Promise<InteractionSummary[]> {
  const query = new URLSearchParams();
  if (params.limit != null) query.set("limit", String(params.limit));
  if (params.offset != null) query.set("offset", String(params.offset));
  if (params.provider) query.set("provider", params.provider);
  if (params.model) query.set("model", params.model);
  if (params.session_id) query.set("session_id", params.session_id);
  const qs = query.toString();
  const url = `/_interceptor/interactions${qs ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to list interactions: ${res.status}`);
  return res.json();
}

export async function getInteraction(id: string): Promise<Interaction> {
  const res = await fetch(`/api/interactions/${id}`);
  if (!res.ok) throw new Error(`Failed to get interaction ${id}: ${res.status}`);
  return res.json();
}

export function downloadUrl(id: string): string {
  return `/api/interactions/${id}/download`;
}

export async function getSessions(): Promise<SessionInfo[]> {
  const res = await fetch("/api/sessions");
  if (!res.ok) throw new Error(`Failed to list sessions: ${res.status}`);
  return res.json();
}

export async function getSessionGraph(sessionId: string): Promise<SessionGraph> {
  const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/graph`);
  if (!res.ok) throw new Error(`Failed to get session graph: ${res.status}`);
  return res.json();
}

export async function getSessionToolSequence(sessionId: string): Promise<ToolCallStep[]> {
  const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/tool-sequence`);
  if (!res.ok) throw new Error(`Failed to get tool sequence: ${res.status}`);
  return res.json();
}

export async function getConversations(): Promise<ConversationSummary[]> {
  const res = await fetch("/api/conversations");
  if (!res.ok) throw new Error(`Failed to list conversations: ${res.status}`);
  const data: unknown = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function getConversationTurns(conversationId: string): Promise<ConversationTurn[]> {
  const res = await fetch(`/_interceptor/conversations/${encodeURIComponent(conversationId)}`);
  if (!res.ok) throw new Error(`Failed to get conversation turns: ${res.status}`);
  const data: unknown = await res.json();
  return Array.isArray(data) ? (data as ConversationTurn[]) : [];
}

export async function getAgentGraph(conversationId: string): Promise<AgentGraph> {
  const res = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}/agent-graph`);
  if (!res.ok) throw new Error(`Failed to get agent graph: ${res.status}`);
  const data = await res.json() as Partial<AgentGraph>;
  return {
    conversation_id: data.conversation_id ?? conversationId,
    nodes: Array.isArray(data.nodes) ? data.nodes : [],
    edges: Array.isArray(data.edges) ? data.edges : [],
  };
}

export async function clearInteractions(
  scope: ClearScope,
  sessionId?: string
): Promise<{ deleted: number }> {
  const res = await fetch("/api/interactions/clear", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scope, sessionId }),
  });
  if (!res.ok) throw new Error(`Clear failed: ${res.status}`);
  return res.json();
}
