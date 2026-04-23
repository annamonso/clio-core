#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_floating_point.hpp>

#include "dt_provenance/protocol/interaction.h"

using namespace dt_provenance::protocol;
using Catch::Matchers::WithinAbs;

TEST_CASE("InteractionRecord round-trips through JSON losslessly",
          "[interaction]") {
  InteractionRecord original;
  original.sequence_id = 42;
  original.session_id = "agent-0";
  original.scenario_id = "expt-multi-agent";
  original.host = "ares-comp-11";
  original.timestamp = "2026-03-02T14:30:00.000Z";
  original.provider = Provider::kAnthropic;
  original.model = "claude-sonnet-4-6";

  original.request.method = "POST";
  original.request.path = "/v1/messages";
  original.request.headers = json{{"anthropic-version", "2023-06-01"}};
  original.request.body = json{{"model", "claude-sonnet-4-6"}};
  original.request.system_prompt_hash = "a1b2c3d4";

  original.response.status_code = 200;
  original.response.is_streaming = true;
  original.response.text = "Hello, world!";
  original.response.tool_calls.push_back(
      ToolCall{"toolu_01", "Read", json{{"file", "test.cc"}}});
  original.response.stop_reason = "end_turn";

  original.metrics.input_tokens = 1234;
  original.metrics.output_tokens = 567;
  original.metrics.cache_read_tokens = 800;
  original.metrics.cache_creation_tokens = 0;
  original.metrics.cost_usd = 0.012;
  original.metrics.total_latency_ms = 2345.0;
  original.metrics.time_to_first_token_ms = 123.0;

  original.conversation.conversation_id = "conv-uuid-123";
  original.conversation.parent_sequence_id = 41;
  original.conversation.turn_number = 3;
  original.conversation.turn_type = "continuation";

  original.context_metrics.message_count = 12;
  original.context_metrics.user_turn_count = 4;
  original.context_metrics.assistant_turn_count = 4;
  original.context_metrics.tool_result_count = 4;
  original.context_metrics.context_depth_chars = 15000;

  // Serialize to JSON
  json j = original.ToJson();

  // Deserialize back
  auto restored = InteractionRecord::FromJson(j);

  // Verify all fields
  REQUIRE(restored.sequence_id == 42);
  REQUIRE(restored.session_id == "agent-0");
  REQUIRE(restored.scenario_id == "expt-multi-agent");
  REQUIRE(restored.host == "ares-comp-11");
  REQUIRE(restored.timestamp == "2026-03-02T14:30:00.000Z");
  REQUIRE(restored.provider == Provider::kAnthropic);
  REQUIRE(restored.model == "claude-sonnet-4-6");

  REQUIRE(restored.request.method == "POST");
  REQUIRE(restored.request.path == "/v1/messages");
  REQUIRE(restored.request.headers["anthropic-version"] == "2023-06-01");
  REQUIRE(restored.request.system_prompt_hash == "a1b2c3d4");

  REQUIRE(restored.response.status_code == 200);
  REQUIRE(restored.response.is_streaming == true);
  REQUIRE(restored.response.text == "Hello, world!");
  REQUIRE(restored.response.tool_calls.size() == 1);
  REQUIRE(restored.response.tool_calls[0].id == "toolu_01");
  REQUIRE(restored.response.tool_calls[0].name == "Read");
  REQUIRE(restored.response.tool_calls[0].input["file"] == "test.cc");
  REQUIRE(restored.response.stop_reason == "end_turn");

  REQUIRE(restored.metrics.input_tokens == 1234);
  REQUIRE(restored.metrics.output_tokens == 567);
  REQUIRE(restored.metrics.cache_read_tokens == 800);
  REQUIRE(restored.metrics.cache_creation_tokens == 0);
  REQUIRE_THAT(restored.metrics.cost_usd, WithinAbs(0.012, 0.0001));
  REQUIRE_THAT(restored.metrics.total_latency_ms, WithinAbs(2345.0, 0.1));
  REQUIRE_THAT(restored.metrics.time_to_first_token_ms, WithinAbs(123.0, 0.1));

  REQUIRE(restored.conversation.conversation_id == "conv-uuid-123");
  REQUIRE(restored.conversation.parent_sequence_id == 41);
  REQUIRE(restored.conversation.turn_number == 3);
  REQUIRE(restored.conversation.turn_type == "continuation");

  REQUIRE(restored.context_metrics.message_count == 12);
  REQUIRE(restored.context_metrics.user_turn_count == 4);
  REQUIRE(restored.context_metrics.assistant_turn_count == 4);
  REQUIRE(restored.context_metrics.tool_result_count == 4);
  REQUIRE(restored.context_metrics.context_depth_chars == 15000);
}

TEST_CASE("InteractionRecord::FromJson handles missing fields gracefully",
          "[interaction]") {
  json j = {{"sequence_id", 1}, {"session_id", "test"}};
  auto record = InteractionRecord::FromJson(j);

  REQUIRE(record.sequence_id == 1);
  REQUIRE(record.session_id == "test");
  REQUIRE(record.model.empty());
  REQUIRE(record.provider == Provider::kUnknown);
  REQUIRE(record.response.status_code == 0);
  REQUIRE(record.response.tool_calls.empty());
}

TEST_CASE("TokenUsage round-trips through JSON", "[interaction]") {
  TokenUsage original;
  original.input_tokens = 100;
  original.output_tokens = 50;
  original.cache_creation_tokens = 10;
  original.cache_read_tokens = 20;
  original.total_tokens = 180;

  auto j = original.ToJson();
  auto restored = TokenUsage::FromJson(j);

  REQUIRE(restored.input_tokens == 100);
  REQUIRE(restored.output_tokens == 50);
  REQUIRE(restored.cache_creation_tokens == 10);
  REQUIRE(restored.cache_read_tokens == 20);
  REQUIRE(restored.total_tokens == 180);
}

TEST_CASE("ToolCall round-trips through JSON", "[interaction]") {
  ToolCall original;
  original.id = "tc_01";
  original.name = "Read";
  original.input = json{{"path", "/tmp/test.txt"}};

  auto j = original.ToJson();
  auto restored = ToolCall::FromJson(j);

  REQUIRE(restored.id == "tc_01");
  REQUIRE(restored.name == "Read");
  REQUIRE(restored.input["path"] == "/tmp/test.txt");
}

TEST_CASE("ConversationInfo round-trips through JSON", "[interaction]") {
  ConversationInfo original;
  original.conversation_id = "conv-123";
  original.parent_sequence_id = 5;
  original.turn_number = 3;
  original.turn_type = "tool_result";

  auto j = original.ToJson();
  auto restored = ConversationInfo::FromJson(j);

  REQUIRE(restored.conversation_id == "conv-123");
  REQUIRE(restored.parent_sequence_id == 5);
  REQUIRE(restored.turn_number == 3);
  REQUIRE(restored.turn_type == "tool_result");
}

TEST_CASE("InteractionRecord ToJson produces valid ordered JSON",
          "[interaction]") {
  InteractionRecord record;
  record.sequence_id = 1;
  record.session_id = "test";
  record.provider = Provider::kOpenAI;

  json j = record.ToJson();

  // Verify it can be serialized to string and back
  std::string serialized = j.dump(2);
  REQUIRE_FALSE(serialized.empty());

  auto reparsed = json::parse(serialized);
  REQUIRE(reparsed["sequence_id"] == 1);
  REQUIRE(reparsed["provider"] == "openai");
}
