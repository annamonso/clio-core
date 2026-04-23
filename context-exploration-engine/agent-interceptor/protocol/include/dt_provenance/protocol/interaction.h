#ifndef DT_PROVENANCE_PROTOCOL_INTERACTION_H_
#define DT_PROVENANCE_PROTOCOL_INTERACTION_H_

#include <cstdint>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

#include "provider.h"

namespace dt_provenance::protocol {

using json = nlohmann::ordered_json;

/**
 * Token usage from an LLM response
 */
struct TokenUsage {
  int64_t input_tokens = 0;
  int64_t output_tokens = 0;
  int64_t cache_creation_tokens = 0;
  int64_t cache_read_tokens = 0;
  int64_t total_tokens = 0;

  /** Serialize to JSON */
  json ToJson() const;

  /** Deserialize from JSON */
  static TokenUsage FromJson(const json& j);
};

/**
 * Cost estimate for an LLM interaction
 */
struct CostEstimate {
  double input_cost = 0.0;
  double output_cost = 0.0;
  double total_cost = 0.0;
  std::string model;
  std::string note;

  /** Serialize to JSON */
  json ToJson() const;

  /** Deserialize from JSON */
  static CostEstimate FromJson(const json& j);
};

/**
 * A single tool call extracted from a response
 */
struct ToolCall {
  std::string id;
  std::string name;
  json input;

  /** Serialize to JSON */
  json ToJson() const;

  /** Deserialize from JSON */
  static ToolCall FromJson(const json& j);
};

/**
 * Context metrics about the conversation state
 */
struct ContextMetrics {
  int32_t message_count = 0;
  int32_t user_turn_count = 0;
  int32_t assistant_turn_count = 0;
  int32_t tool_result_count = 0;
  int64_t context_depth_chars = 0;
  int32_t new_messages_this_turn = 0;
  int64_t system_prompt_length = 0;
  std::string system_prompt_hash;

  /** Serialize to JSON */
  json ToJson() const;

  /** Deserialize from JSON */
  static ContextMetrics FromJson(const json& j);
};

/**
 * Conversation threading information
 */
struct ConversationInfo {
  std::string conversation_id;
  uint64_t parent_sequence_id = 0;
  int32_t turn_number = 0;
  std::string turn_type;  // "initial", "continuation", "tool_result", "handoff"

  /** Serialize to JSON */
  json ToJson() const;

  /** Deserialize from JSON */
  static ConversationInfo FromJson(const json& j);
};

/**
 * Complete interaction record for one LLM API request/response cycle
 *
 * Ported from Python agent-interception models.py Interaction class.
 * This is the blob data stored in CTE.
 */
struct InteractionRecord {
  // Identity
  uint64_t sequence_id = 0;
  std::string session_id;
  std::string scenario_id;  // Multi-agent scenario tag (empty if unused)
  std::string host;         // Hostname of the agent that emitted this request
  std::string timestamp;  // ISO 8601
  Provider provider = Provider::kUnknown;
  std::string model;

  // Request
  struct {
    std::string method;
    std::string path;
    json headers;
    json body;
    std::string system_prompt_hash;
  } request;

  // Response
  struct {
    int32_t status_code = 0;
    bool is_streaming = false;
    std::string text;
    std::vector<ToolCall> tool_calls;
    std::string stop_reason;
  } response;

  // Metrics
  struct {
    int64_t input_tokens = 0;
    int64_t output_tokens = 0;
    int64_t cache_read_tokens = 0;
    int64_t cache_creation_tokens = 0;
    double cost_usd = 0.0;
    double total_latency_ms = 0.0;         // LLM round-trip time (excl. CEE)
    double time_to_first_token_ms = 0.0;
    // CEE overhead fields — time added by interception pipeline
    double proxy_overhead_ms = 0.0;        // request parsing + record building
    double tracker_store_ms = 0.0;         // CTE store time in tracker
    double ctx_untangler_ms = 0.0;         // diff computation in ctx_untangler
  } metrics;

  // Conversation threading
  ConversationInfo conversation;

  // Context metrics
  ContextMetrics context_metrics;

  /** Serialize to JSON */
  json ToJson() const;

  /** Deserialize from JSON */
  static InteractionRecord FromJson(const json& j);
};

}  // namespace dt_provenance::protocol

#endif  // DT_PROVENANCE_PROTOCOL_INTERACTION_H_
