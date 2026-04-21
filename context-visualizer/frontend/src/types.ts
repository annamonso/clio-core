export type Provider = "openai" | "anthropic" | "ollama" | "unknown";

export interface StreamChunk {
  index: number;
  timestamp: string;
  data: string;
  parsed: Record<string, unknown> | null;
  delta_text: string | null;
}

export interface TokenUsage {
  input_tokens: number | null;
  output_tokens: number | null;
  cache_creation_tokens: number | null;
  cache_read_tokens: number | null;
  total_tokens: number | null;
}

export interface ImageMetadata {
  count: number;
  media_types: string[];
  approximate_sizes: number[];
}

export interface CostEstimate {
  input_cost: number;
  output_cost: number;
  total_cost: number;
  model: string | null;
  note: string | null;
}

export interface Interaction {
  id: string;
  session_id: string | null;
  timestamp: string;

  // Request
  method: string;
  path: string;
  request_headers: Record<string, string>;
  request_body: Record<string, unknown> | null;
  raw_request_body: string | null;

  // Provider
  provider: Provider;
  model: string | null;

  // Parsed request content
  system_prompt: string | null;
  messages: Record<string, unknown>[] | null;
  tools: Record<string, unknown>[] | null;
  image_metadata: ImageMetadata | null;

  // Response
  status_code: number | null;
  response_headers: Record<string, string>;
  response_body: Record<string, unknown> | null;
  raw_response_body: string | null;
  is_streaming: boolean;

  // Stream data
  stream_chunks: StreamChunk[];

  // Extracted content
  response_text: string | null;
  tool_calls: Record<string, unknown>[] | null;

  // Metrics
  token_usage: TokenUsage | null;
  cost_estimate: CostEstimate | null;
  time_to_first_token_ms: number | null;
  total_latency_ms: number | null;

  // Error
  error: string | null;
}

export interface InteractionSummary {
  id: string;
  session_id: string | null;
  timestamp: string;
  provider: Provider;
  model: string | null;
  method: string;
  path: string;
  status_code: number | null;
  is_streaming: boolean;
  total_latency_ms: number | null;
  response_text_preview: string | null;
}

export interface SessionInfo {
  sessionId: string;
  startTime: string;
  endTime: string;
  interactionCount: number;
  providers: string[];
  models: string[];
}

export interface NodeMetrics {
  callCount: number;
  errorRate: number;
  avgLatencyMs: number | null;
  p95LatencyMs: number | null;
  totalTokens: number;
  totalCostUsd: number;
}

export interface GraphNode {
  id: string;
  type: "agent" | "proxy" | "provider" | "model" | "tool";
  label: string;
  metrics: NodeMetrics;
}

export interface GraphEdge {
  from: string;
  to: string;
  callCount: number;
  errorRate: number;
  avgLatencyMs: number | null;
  p95LatencyMs: number | null;
  totalTokens: number;
  totalCostUsd: number;
}

export interface TimelineEntry {
  interactionId: string;
  timestamp: string;
  status: number | null;
  latencyMs: number | null;
  provider: string;
  isStreaming: boolean;
  error: string | null;
}

export interface SessionGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  timeline: TimelineEntry[];
}

export interface AgentNode {
  session_id: string;
  agent_role: string | null;
  interaction_count: number;
  total_tokens: number;
  total_cost_usd: number;
}

export interface AgentEdge {
  from_session_id: string;
  to_session_id: string;
  interaction_id: string;
  turn_number: number;
  latency_ms: number | null;
}

export interface AgentGraph {
  conversation_id: string;
  nodes: AgentNode[];
  edges: AgentEdge[];
}

export interface ConversationSummary {
  conversationId: string;
  turnCount: number;
  firstTurn: string;
  lastTurn: string;
}

export interface ConversationTurn {
  id: string;
  session_id: string | null;
  turn_number: number;
  turn_type: string | null;
  timestamp: string;
  provider: string;
  model: string | null;
  parent_interaction_id: string | null;
  context_metrics: Record<string, unknown> | null;
  response_text_preview: string | null;
  tool_calls: Record<string, unknown>[] | null;
  total_latency_ms: number | null;
}

export type ClearScope = "all" | "24h" | "session";

export interface ToolCallInfo {
  id: string | null;
  name: string | null;
  input: Record<string, unknown>;
}

export interface ToolResultInfo {
  toolCallId: string | null;
  content: string;
}

export interface ToolCallStep {
  interactionId: string;
  interactionIndex: number;
  timestamp: string;
  provider: string;
  model: string | null;
  latencyMs: number | null;
  statusCode: number | null;
  error: string | null;
  toolCalls: ToolCallInfo[];
  toolResults: ToolResultInfo[];
  responseText: string | null;
  systemPromptPreview: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
}
