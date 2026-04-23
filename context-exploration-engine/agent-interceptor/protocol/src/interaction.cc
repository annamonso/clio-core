#include "dt_provenance/protocol/interaction.h"

namespace dt_provenance::protocol {

// --- TokenUsage ---

json TokenUsage::ToJson() const {
  return json{
      {"input_tokens", input_tokens},
      {"output_tokens", output_tokens},
      {"cache_creation_tokens", cache_creation_tokens},
      {"cache_read_tokens", cache_read_tokens},
      {"total_tokens", total_tokens}};
}

TokenUsage TokenUsage::FromJson(const json& j) {
  TokenUsage u;
  if (j.contains("input_tokens")) u.input_tokens = j["input_tokens"].get<int64_t>();
  if (j.contains("output_tokens")) u.output_tokens = j["output_tokens"].get<int64_t>();
  if (j.contains("cache_creation_tokens")) u.cache_creation_tokens = j["cache_creation_tokens"].get<int64_t>();
  if (j.contains("cache_read_tokens")) u.cache_read_tokens = j["cache_read_tokens"].get<int64_t>();
  if (j.contains("total_tokens")) u.total_tokens = j["total_tokens"].get<int64_t>();
  return u;
}

// --- CostEstimate ---

json CostEstimate::ToJson() const {
  return json{
      {"input_cost", input_cost},
      {"output_cost", output_cost},
      {"total_cost", total_cost},
      {"model", model},
      {"note", note}};
}

CostEstimate CostEstimate::FromJson(const json& j) {
  CostEstimate c;
  if (j.contains("input_cost")) c.input_cost = j["input_cost"].get<double>();
  if (j.contains("output_cost")) c.output_cost = j["output_cost"].get<double>();
  if (j.contains("total_cost")) c.total_cost = j["total_cost"].get<double>();
  if (j.contains("model")) c.model = j["model"].get<std::string>();
  if (j.contains("note")) c.note = j["note"].get<std::string>();
  return c;
}

// --- ToolCall ---

json ToolCall::ToJson() const {
  return json{{"id", id}, {"name", name}, {"input", input}};
}

ToolCall ToolCall::FromJson(const json& j) {
  ToolCall tc;
  if (j.contains("id")) tc.id = j["id"].get<std::string>();
  if (j.contains("name")) tc.name = j["name"].get<std::string>();
  if (j.contains("input")) tc.input = j["input"];
  return tc;
}

// --- ContextMetrics ---

json ContextMetrics::ToJson() const {
  return json{
      {"message_count", message_count},
      {"user_turn_count", user_turn_count},
      {"assistant_turn_count", assistant_turn_count},
      {"tool_result_count", tool_result_count},
      {"context_depth_chars", context_depth_chars},
      {"new_messages_this_turn", new_messages_this_turn},
      {"system_prompt_length", system_prompt_length},
      {"system_prompt_hash", system_prompt_hash}};
}

ContextMetrics ContextMetrics::FromJson(const json& j) {
  ContextMetrics m;
  if (j.contains("message_count")) m.message_count = j["message_count"].get<int32_t>();
  if (j.contains("user_turn_count")) m.user_turn_count = j["user_turn_count"].get<int32_t>();
  if (j.contains("assistant_turn_count")) m.assistant_turn_count = j["assistant_turn_count"].get<int32_t>();
  if (j.contains("tool_result_count")) m.tool_result_count = j["tool_result_count"].get<int32_t>();
  if (j.contains("context_depth_chars")) m.context_depth_chars = j["context_depth_chars"].get<int64_t>();
  if (j.contains("new_messages_this_turn")) m.new_messages_this_turn = j["new_messages_this_turn"].get<int32_t>();
  if (j.contains("system_prompt_length")) m.system_prompt_length = j["system_prompt_length"].get<int64_t>();
  if (j.contains("system_prompt_hash")) m.system_prompt_hash = j["system_prompt_hash"].get<std::string>();
  return m;
}

// --- ConversationInfo ---

json ConversationInfo::ToJson() const {
  return json{
      {"conversation_id", conversation_id},
      {"parent_sequence_id", parent_sequence_id},
      {"turn_number", turn_number},
      {"turn_type", turn_type}};
}

ConversationInfo ConversationInfo::FromJson(const json& j) {
  ConversationInfo c;
  if (j.contains("conversation_id")) c.conversation_id = j["conversation_id"].get<std::string>();
  if (j.contains("parent_sequence_id")) c.parent_sequence_id = j["parent_sequence_id"].get<uint64_t>();
  if (j.contains("turn_number")) c.turn_number = j["turn_number"].get<int32_t>();
  if (j.contains("turn_type")) c.turn_type = j["turn_type"].get<std::string>();
  return c;
}

// --- InteractionRecord ---

json InteractionRecord::ToJson() const {
  // Build tool_calls array
  json tool_calls_json = json::array();
  for (const auto& tc : response.tool_calls) {
    tool_calls_json.push_back(tc.ToJson());
  }

  return json{
      {"sequence_id", sequence_id},
      {"session_id", session_id},
      {"scenario_id", scenario_id},
      {"host", host},
      {"timestamp", timestamp},
      {"provider", ProviderToString(provider)},
      {"model", model},
      {"request",
       json{{"method", request.method},
            {"path", request.path},
            {"headers", request.headers},
            {"body", request.body},
            {"system_prompt_hash", request.system_prompt_hash}}},
      {"response",
       json{{"status_code", response.status_code},
            {"is_streaming", response.is_streaming},
            {"text", response.text},
            {"tool_calls", tool_calls_json},
            {"stop_reason", response.stop_reason}}},
      {"metrics",
       json{{"input_tokens", metrics.input_tokens},
            {"output_tokens", metrics.output_tokens},
            {"cache_read_tokens", metrics.cache_read_tokens},
            {"cache_creation_tokens", metrics.cache_creation_tokens},
            {"cost_usd", metrics.cost_usd},
            {"total_latency_ms", metrics.total_latency_ms},
            {"time_to_first_token_ms", metrics.time_to_first_token_ms},
            {"proxy_overhead_ms", metrics.proxy_overhead_ms},
            {"tracker_store_ms", metrics.tracker_store_ms},
            {"ctx_untangler_ms", metrics.ctx_untangler_ms}}},
      {"conversation", conversation.ToJson()},
      {"context_metrics", context_metrics.ToJson()}};
}

InteractionRecord InteractionRecord::FromJson(const json& j) {
  InteractionRecord r;

  if (j.contains("sequence_id")) r.sequence_id = j["sequence_id"].get<uint64_t>();
  if (j.contains("session_id")) r.session_id = j["session_id"].get<std::string>();
  if (j.contains("scenario_id")) r.scenario_id = j["scenario_id"].get<std::string>();
  if (j.contains("host")) r.host = j["host"].get<std::string>();
  if (j.contains("timestamp")) r.timestamp = j["timestamp"].get<std::string>();
  if (j.contains("provider")) r.provider = ProviderFromString(j["provider"].get<std::string>());
  if (j.contains("model")) r.model = j["model"].get<std::string>();

  // Request
  if (j.contains("request")) {
    const auto& req = j["request"];
    if (req.contains("method")) r.request.method = req["method"].get<std::string>();
    if (req.contains("path")) r.request.path = req["path"].get<std::string>();
    if (req.contains("headers")) r.request.headers = req["headers"];
    if (req.contains("body")) r.request.body = req["body"];
    if (req.contains("system_prompt_hash")) r.request.system_prompt_hash = req["system_prompt_hash"].get<std::string>();
  }

  // Response
  if (j.contains("response")) {
    const auto& resp = j["response"];
    if (resp.contains("status_code")) r.response.status_code = resp["status_code"].get<int32_t>();
    if (resp.contains("is_streaming")) r.response.is_streaming = resp["is_streaming"].get<bool>();
    if (resp.contains("text")) r.response.text = resp["text"].get<std::string>();
    if (resp.contains("tool_calls")) {
      for (const auto& tc : resp["tool_calls"]) {
        r.response.tool_calls.push_back(ToolCall::FromJson(tc));
      }
    }
    if (resp.contains("stop_reason")) r.response.stop_reason = resp["stop_reason"].get<std::string>();
  }

  // Metrics
  if (j.contains("metrics")) {
    const auto& m = j["metrics"];
    if (m.contains("input_tokens")) r.metrics.input_tokens = m["input_tokens"].get<int64_t>();
    if (m.contains("output_tokens")) r.metrics.output_tokens = m["output_tokens"].get<int64_t>();
    if (m.contains("cache_read_tokens")) r.metrics.cache_read_tokens = m["cache_read_tokens"].get<int64_t>();
    if (m.contains("cache_creation_tokens")) r.metrics.cache_creation_tokens = m["cache_creation_tokens"].get<int64_t>();
    if (m.contains("cost_usd")) r.metrics.cost_usd = m["cost_usd"].get<double>();
    if (m.contains("total_latency_ms")) r.metrics.total_latency_ms = m["total_latency_ms"].get<double>();
    if (m.contains("time_to_first_token_ms")) r.metrics.time_to_first_token_ms = m["time_to_first_token_ms"].get<double>();
    if (m.contains("proxy_overhead_ms")) r.metrics.proxy_overhead_ms = m["proxy_overhead_ms"].get<double>();
    if (m.contains("tracker_store_ms")) r.metrics.tracker_store_ms = m["tracker_store_ms"].get<double>();
    if (m.contains("ctx_untangler_ms")) r.metrics.ctx_untangler_ms = m["ctx_untangler_ms"].get<double>();
  }

  // Conversation
  if (j.contains("conversation")) {
    r.conversation = ConversationInfo::FromJson(j["conversation"]);
  }

  // Context metrics
  if (j.contains("context_metrics")) {
    r.context_metrics = ContextMetrics::FromJson(j["context_metrics"]);
  }

  return r;
}

}  // namespace dt_provenance::protocol
