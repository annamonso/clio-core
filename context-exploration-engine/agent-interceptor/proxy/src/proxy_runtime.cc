#include "dt_provenance/proxy/proxy_runtime.h"

#include <algorithm>
#include <chrono>
#include <unistd.h>

#define CPPHTTPLIB_OPENSSL_SUPPORT
#include <httplib.h>
#include <nlohmann/json.hpp>
#include <hermes_shm/serialize/msgpack_wrapper.h>

#include <wrp_cte/core/core_client.h>
#include <cstring>

#include "dt_provenance/protocol/anthropic_parser.h"
#include "dt_provenance/protocol/openai_parser.h"
#include "dt_provenance/protocol/cost_estimator.h"
#include "dt_provenance/protocol/interaction.h"
#include "dt_provenance/protocol/provider.h"
#include "dt_provenance/protocol/stream_reassembly.h"
#include "dt_provenance/tracker/tracker_client.h"

namespace dt_provenance::proxy {

using json = nlohmann::ordered_json;
using namespace dt_provenance::protocol;

Runtime::~Runtime() = default;

/**
 * Parse a URL into host, port, and ssl flag
 */
static void ParseUpstreamUrl(const std::string& url, std::string& host,
                             int& port, bool& ssl) {
  if (url.starts_with("https://")) {
    ssl = true;
    host = url.substr(8);
    port = 443;
  } else if (url.starts_with("http://")) {
    ssl = false;
    host = url.substr(7);
    port = 80;
  } else {
    host = url;
    port = 443;
    ssl = true;
  }
  auto colon = host.find(':');
  if (colon != std::string::npos) {
    port = std::stoi(host.substr(colon + 1));
    host = host.substr(0, colon);
  }
  if (!host.empty() && host.back() == '/') host.pop_back();
}

/**
 * Select upstream URL based on provider
 */
static std::string SelectUpstream(Provider provider) {
  switch (provider) {
    case Provider::kAnthropic: return "https://api.anthropic.com";
    case Provider::kOpenAI:    return "https://api.openai.com";
    case Provider::kOllama:    return "http://localhost:11434";
    default:                   return "";
  }
}

/**
 * Forward request directly to upstream and return response.
 * Now runs on Chimaera worker threads via Monitor handler.
 */
static void ForwardDirect(const std::string& upstream_url,
                          const std::string& path,
                          const std::string& headers_json_str,
                          const std::string& request_body,
                          int& resp_status, std::string& resp_headers_out,
                          std::string& resp_body_out,
                          double& latency_ms) {
  std::string host;
  int port;
  bool ssl;
  ParseUpstreamUrl(upstream_url, host, port, ssl);

  // Build headers from JSON
  json request_headers;
  try {
    request_headers = json::parse(headers_json_str);
  } catch (...) {
    request_headers = json::object();
  }

  httplib::Headers hdr;
  for (auto& [k, v] : request_headers.items()) {
    if (v.is_string()) {
      hdr.emplace(k, v.get<std::string>());
    }
  }

  auto start = std::chrono::steady_clock::now();

  std::string response_body;
  int response_status = 502;
  httplib::Headers response_headers;

  if (ssl) {
    httplib::SSLClient cli(host, port);
    cli.set_connection_timeout(30);
    cli.set_read_timeout(300);
    cli.enable_server_certificate_verification(false);

    auto res = cli.Post(path, hdr, request_body, "application/json");
    if (res) {
      response_status = res->status;
      response_body = res->body;
      response_headers = res->headers;
    }
  } else {
    httplib::Client cli(host, port);
    cli.set_connection_timeout(30);
    cli.set_read_timeout(300);

    auto res = cli.Post(path, hdr, request_body, "application/json");
    if (res) {
      response_status = res->status;
      response_body = res->body;
      response_headers = res->headers;
    }
  }

  auto end = std::chrono::steady_clock::now();
  latency_ms = std::chrono::duration<double, std::milli>(end - start).count();

  // Serialize response headers (normalize keys to lowercase for consistent lookup)
  json resp_hdrs_json = json::object();
  for (const auto& [k, v] : response_headers) {
    std::string lower_k = k;
    std::transform(lower_k.begin(), lower_k.end(), lower_k.begin(), ::tolower);
    resp_hdrs_json[lower_k] = v;
  }

  resp_status = response_status;
  resp_headers_out = resp_hdrs_json.dump();
  resp_body_out = response_body;
}

/**
 * Build an interaction record JSON from request/response data
 */
static std::string LocalHostname() {
  char buf[256];
  if (gethostname(buf, sizeof(buf)) == 0) {
    buf[sizeof(buf) - 1] = '\0';
    return std::string(buf);
  }
  return std::string();
}

// ISO-8601 UTC timestamp (millisecond precision). Populates
// InteractionRecord::timestamp so the visualizer's timeline has a stable
// sort key — without this, records written by the proxy's BuildInteractionRecord
// path (the common path) had timestamp="" and the workspace timeline rendered
// blank. Mirrors the helper in the anthropic interceptor (commit 1bc7c447).
static std::string IsoNowUtc() {
  using clock = std::chrono::system_clock;
  auto now = clock::now();
  auto t = clock::to_time_t(now);
  auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                now.time_since_epoch()) % 1000;
  std::tm tm_utc{};
  gmtime_r(&t, &tm_utc);
  char buf[40];
  std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm_utc);
  char out[48];
  std::snprintf(out, sizeof(out), "%s.%03lldZ", buf,
                static_cast<long long>(ms.count()));
  return out;
}

static std::string BuildInteractionRecord(
    const std::string& session_id, const std::string& scenario_id,
    const std::string& agent_host, Provider provider,
    const std::string& path, const std::string& headers_json_str,
    const std::string& request_body, int response_status,
    const std::string& resp_headers_str, const std::string& resp_body,
    double latency_ms) {
  InteractionRecord record;
  record.session_id = session_id;
  record.scenario_id = scenario_id;
  record.host = agent_host.empty() ? LocalHostname() : agent_host;
  // Wall-clock timestamp at record-build time. Required by the workspace
  // timeline — an empty string here makes the playhead + lane rendering
  // collapse to width 0.
  record.timestamp = IsoNowUtc();
  record.provider = provider;
  record.request.method = "POST";
  record.request.path = path;

  json request_headers;
  try { request_headers = json::parse(headers_json_str); } catch (...) {}
  record.request.headers = request_headers;

  // Parse request body
  try {
    auto req_body = json::parse(request_body);
    if (provider == Provider::kAnthropic) {
      AnthropicParser::ParseRequest(req_body, record);
    } else if (provider == Provider::kOpenAI) {
      OpenAIParser::ParseRequest(req_body, record);
    }
  } catch (...) {}

  // Parse response
  if (response_status >= 200 && response_status < 300) {
    json resp_hdrs;
    try { resp_hdrs = json::parse(resp_headers_str); } catch (...) {}

    bool is_sse = false;
    if (resp_hdrs.contains("content-type")) {
      std::string ct = resp_hdrs["content-type"].get<std::string>();
      is_sse = ct.find("text/event-stream") != std::string::npos;
    }

    if (is_sse) {
      record.response.is_streaming = true;
      auto chunks = ReassembleSSE(resp_body);
      for (const auto& chunk : chunks) {
        if (provider == Provider::kAnthropic)
          AnthropicParser::ParseStreamChunk(chunk, record);
      }
    } else {
      record.response.is_streaming = false;
      try {
        auto body = json::parse(resp_body);
        if (provider == Provider::kAnthropic)
          AnthropicParser::ParseResponse(body, record);
        else if (provider == Provider::kOpenAI)
          OpenAIParser::ParseResponse(body, record);
      } catch (...) {}
    }

    // Estimate cost
    TokenUsage usage;
    usage.input_tokens = record.metrics.input_tokens;
    usage.output_tokens = record.metrics.output_tokens;
    usage.cache_creation_tokens = record.metrics.cache_creation_tokens;
    usage.cache_read_tokens = record.metrics.cache_read_tokens;
    auto cost = CostEstimator::Estimate(provider, record.model, usage);
    record.metrics.cost_usd = cost.total_cost;
  } else {
    // Error response — surface status + error preview so the dashboard
    // can render the failure. Upstream error bodies are normally small
    // JSON, but truncate to keep rogue payloads bounded.
    record.response.is_streaming = false;
    constexpr size_t kMaxErrPreview = 2048;
    if (resp_body.size() > kMaxErrPreview) {
      record.response.text = resp_body.substr(0, kMaxErrPreview) + "…[truncated]";
    } else {
      record.response.text = resp_body;
    }
    record.response.stop_reason = "error";
  }

  record.metrics.total_latency_ms = latency_ms;
  record.metrics.time_to_first_token_ms = latency_ms;
  record.response.status_code = response_status;

  return record.ToJson().dump();
}

chi::TaskResume Runtime::Create(hipc::FullPtr<CreateTask> task,
                                chi::RunContext& rctx) {
  start_time_ = std::chrono::steady_clock::now();
  total_requests_.store(0);

  // Initialize the CTE client with the correct pool ID.
  // The global g_cte_client may be uninitialized (pool_id=0:0) when accessed
  // from a dlopen'd ChiMod .so because the demo server's init doesn't
  // propagate across symbol scopes.
  {
    auto *cte = WRP_CTE_CLIENT;
    if (cte->pool_id_.IsNull()) {
      chi::PoolId cte_pool = CHI_POOL_MANAGER->FindPoolByName("cte_main");
      if (!cte_pool.IsNull()) {
        cte->Init(cte_pool);
        HLOG(kInfo, "Proxy: initialized CTE client with pool_id={}", cte_pool);
      }
    }
  }

  HLOG(kInfo, "DTProvenance proxy ChiMod loaded (Monitor-based dispatch)");
  (void)task;
  (void)rctx;
  co_return;
}

bool Runtime::EnsureTrackerClient() {
  if (tracker_initialized_) return true;
  chi::PoolId pool = CHI_POOL_MANAGER->FindPoolByName("dt_tracker_pool");
  if (!pool.IsNull()) {
    tracker_client_ = std::make_unique<tracker::Client>(pool);
    tracker_initialized_ = true;
    return true;
  }
  return false;
}

// ── Monitor handler ─────────────────────────────────────────────────────

chi::TaskResume Runtime::Monitor(hipc::FullPtr<MonitorTask> task,
                                 chi::RunContext& rctx) {
  std::string query_str(task->query_);

  // 1. Try JSON-encoded forward request — dispatch to I/O worker
  if (!query_str.empty() && query_str[0] == '{') {
    try {
      auto query = json::parse(query_str);
      if (query.contains("action") && query["action"] == "forward") {
        // co_await yields Worker 0; ForwardHttp runs on I/O worker (1-5)
        auto forward_future = client_.AsyncForwardHttp(
            chi::PoolQuery::Local(), query_str);
        co_await forward_future;
        task->results_[container_id_] =
            std::string(forward_future->response_msgpack_.str());
        std::string record_json(forward_future->record_json_.str());
        // Store interaction via tracker — time the full pipeline overhead
        if (!record_json.empty() && EnsureTrackerClient()) {
          try {
            const bool logging = overhead_logging_.load(std::memory_order_relaxed);
            auto pipeline_start = logging ? std::chrono::steady_clock::now()
                                          : std::chrono::steady_clock::time_point{};
            auto store_future = tracker_client_->AsyncStoreInteraction(
                chi::PoolQuery::Local(), record_json);
            co_await store_future;
            if (logging) {
              auto pipeline_end = std::chrono::steady_clock::now();
              uint64_t pipeline_us = static_cast<uint64_t>(
                  std::chrono::duration_cast<std::chrono::microseconds>(
                      pipeline_end - pipeline_start).count());
              total_pipeline_overhead_us_.fetch_add(pipeline_us,
                                                     std::memory_order_relaxed);
            }
          } catch (...) {
            HLOG(kWarning, "Tracker store failed");
          }
        }
        task->SetReturnCode(0);
        co_return;
      }
    } catch (const json::parse_error&) {}
  }

  // 2a. Overhead logging toggle / status
  if (query_str == "overhead_logging:on") {
    overhead_logging_.store(true, std::memory_order_relaxed);
    msgpack::sbuffer sbuf; msgpack::packer<msgpack::sbuffer> pk(sbuf);
    pk.pack_map(1); pk.pack("enabled"); pk.pack(true);
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0); co_return;
  }
  if (query_str == "overhead_logging:off") {
    overhead_logging_.store(false, std::memory_order_relaxed);
    msgpack::sbuffer sbuf; msgpack::packer<msgpack::sbuffer> pk(sbuf);
    pk.pack_map(1); pk.pack("enabled"); pk.pack(false);
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0); co_return;
  }
  if (query_str == "overhead_logging:status") {
    msgpack::sbuffer sbuf; msgpack::packer<msgpack::sbuffer> pk(sbuf);
    pk.pack_map(1); pk.pack("enabled");
    pk.pack(overhead_logging_.load(std::memory_order_relaxed));
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0); co_return;
  }

  // 2. dispatch_stats — local only, no sub-dispatch
  if (query_str == "dispatch_stats") {
    HandleDispatchStats(task);
    task->SetReturnCode(0);
    co_return;
  }

  // 3. Tracker queries — direct CTE access (avoids 2-level inline dispatch)
  if (query_str == "list_sessions") {
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    try {
      auto future = WRP_CTE_CLIENT->AsyncTagQuery(
          "Agentic_session_.*", 0);
      co_await future;
      auto tag_names = future->results_;
      const std::string prefix = "Agentic_session_";
      pk.pack_array(static_cast<uint32_t>(tag_names.size()));
      for (const auto& tag_name : tag_names) {
        std::string session_id = tag_name;
        if (session_id.starts_with(prefix))
          session_id = session_id.substr(prefix.size());
        auto tag_future = WRP_CTE_CLIENT->AsyncGetOrCreateTag(tag_name);
        co_await tag_future;
        auto tag_id = tag_future->tag_id_;
        auto blobs_future = WRP_CTE_CLIENT->AsyncGetContainedBlobs(tag_id);
        co_await blobs_future;
        auto& blobs = blobs_future->blob_names_;
        pk.pack_map(3);
        pk.pack("session_id"); pk.pack(session_id);
        pk.pack("count"); pk.pack(static_cast<uint64_t>(blobs.size()));
        pk.pack("tag_name"); pk.pack(tag_name);
      }
    } catch (...) {
      pk.pack_array(0);
    }
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0);
    co_return;
  }

  if (query_str.rfind("query_session://", 0) == 0) {
    std::string session_id = query_str.substr(16);
    std::string tag_name = "Agentic_session_" + session_id;
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    try {
      auto tag_future = WRP_CTE_CLIENT->AsyncGetOrCreateTag(tag_name);
      co_await tag_future;
      auto tag_id = tag_future->tag_id_;
      auto blobs_future = WRP_CTE_CLIENT->AsyncGetContainedBlobs(tag_id);
      co_await blobs_future;
      auto& blobs = blobs_future->blob_names_;
      auto *ipc = CHI_IPC;
      pk.pack_array(static_cast<uint32_t>(blobs.size()));
      for (const auto& bname : blobs) {
        auto size_future = WRP_CTE_CLIENT->AsyncGetBlobSize(tag_id, bname);
        co_await size_future;
        auto size = size_future->size_;
        if (size == 0) { pk.pack("{}"); continue; }
        auto shm = ipc->AllocateBuffer(size);
        if (shm.IsNull()) { pk.pack("{}"); continue; }
        auto get_future = WRP_CTE_CLIENT->AsyncGetBlob(
            tag_id, bname, 0, size, 0, hipc::ShmPtr<>(shm.shm_));
        co_await get_future;
        pk.pack(std::string(reinterpret_cast<char*>(shm.ptr_), size));
        ipc->FreeBuffer(shm);
      }
    } catch (...) {
      pk.pack_array(0);
    }
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0);
    co_return;
  }

  if (query_str.rfind("get_interaction://", 0) == 0) {
    std::string body = query_str.substr(18);
    auto slash = body.find('/');
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    if (slash != std::string::npos) {
      std::string session_id = body.substr(0, slash);
      uint64_t seq_id = std::stoull(body.substr(slash + 1));
      std::string tag_name = "Agentic_session_" + session_id;
      char blob_buf[16];
      snprintf(blob_buf, sizeof(blob_buf), "%010lu",
               static_cast<unsigned long>(seq_id));
      std::string blob_name(blob_buf);
      try {
        auto tag_future = WRP_CTE_CLIENT->AsyncGetOrCreateTag(tag_name);
        co_await tag_future;
        auto tag_id = tag_future->tag_id_;
        auto size_future = WRP_CTE_CLIENT->AsyncGetBlobSize(tag_id, blob_name);
        co_await size_future;
        auto size = size_future->size_;
        if (size > 0) {
          auto *ipc = CHI_IPC;
          auto shm = ipc->AllocateBuffer(size);
          if (shm.IsNull()) { pk.pack("{}"); } else {
          auto get_future = WRP_CTE_CLIENT->AsyncGetBlob(
              tag_id, blob_name, 0, size, 0, hipc::ShmPtr<>(shm.shm_));
          co_await get_future;
          pk.pack(std::string(reinterpret_cast<char*>(shm.ptr_), size));
          ipc->FreeBuffer(shm); }
        } else {
          pk.pack("{}");
        }
      } catch (...) {
        pk.pack("{}");
      }
    } else {
      pk.pack("{}");
    }
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0);
    co_return;
  }

  // 4. Graph queries — direct CTE access
  if (query_str == "list_graphs") {
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    try {
      auto future = WRP_CTE_CLIENT->AsyncTagQuery(
          "Ctx_graph_.*", 0);
      co_await future;
      auto tag_names = future->results_;
      const std::string prefix = "Ctx_graph_";
      pk.pack_array(static_cast<uint32_t>(tag_names.size()));
      for (const auto& tag_name : tag_names) {
        std::string session_id = tag_name;
        if (session_id.starts_with(prefix))
          session_id = session_id.substr(prefix.size());
        pk.pack(session_id);
      }
    } catch (...) {
      pk.pack_array(0);
    }
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0);
    co_return;
  }

  if (query_str.rfind("query_graph://", 0) == 0) {
    std::string body = query_str.substr(14);
    uint64_t since_seq = 0;
    auto qmark = body.find('?');
    std::string session_id;
    if (qmark != std::string::npos) {
      session_id = body.substr(0, qmark);
      std::string params = body.substr(qmark + 1);
      if (params.rfind("since=", 0) == 0) {
        try { since_seq = std::stoull(params.substr(6)); } catch (...) {}
      }
    } else {
      session_id = body;
    }
    std::string graph_tag = "Ctx_graph_" + session_id;
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    try {
      auto tag_future = WRP_CTE_CLIENT->AsyncGetOrCreateTag(graph_tag);
      co_await tag_future;
      auto tag_id = tag_future->tag_id_;
      auto blobs_future = WRP_CTE_CLIENT->AsyncGetContainedBlobs(tag_id);
      co_await blobs_future;
      auto& blobs = blobs_future->blob_names_;
      std::vector<std::string> filtered;
      for (const auto& bname : blobs) {
        if (since_seq > 0) {
          try {
            uint64_t bseq = std::stoull(bname);
            if (bseq <= since_seq) continue;
          } catch (...) {}
        }
        filtered.push_back(bname);
      }
      auto *ipc = CHI_IPC;
      pk.pack_array(static_cast<uint32_t>(filtered.size()));
      for (const auto& bname : filtered) {
        auto size_future = WRP_CTE_CLIENT->AsyncGetBlobSize(tag_id, bname);
        co_await size_future;
        auto size = size_future->size_;
        if (size == 0) { pk.pack("{}"); continue; }
        auto shm = ipc->AllocateBuffer(size);
        if (shm.IsNull()) { pk.pack("{}"); continue; }
        auto get_future = WRP_CTE_CLIENT->AsyncGetBlob(
            tag_id, bname, 0, size, 0, hipc::ShmPtr<>(shm.shm_));
        co_await get_future;
        pk.pack(std::string(reinterpret_cast<char*>(shm.ptr_), size));
        ipc->FreeBuffer(shm);
      }
    } catch (...) {
      pk.pack_array(0);
    }
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0);
    co_return;
  }

  if (query_str.rfind("get_node://", 0) == 0) {
    std::string body = query_str.substr(11);
    auto slash = body.find('/');
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    if (slash != std::string::npos) {
      std::string session_id = body.substr(0, slash);
      uint64_t seq_id = std::stoull(body.substr(slash + 1));
      std::string graph_tag = "Ctx_graph_" + session_id;
      char blob_buf[16];
      snprintf(blob_buf, sizeof(blob_buf), "%010lu",
               static_cast<unsigned long>(seq_id));
      std::string blob_name(blob_buf);
      try {
        auto tag_future = WRP_CTE_CLIENT->AsyncGetOrCreateTag(graph_tag);
        co_await tag_future;
        auto tag_id = tag_future->tag_id_;
        auto size_future = WRP_CTE_CLIENT->AsyncGetBlobSize(tag_id, blob_name);
        co_await size_future;
        auto size = size_future->size_;
        if (size > 0) {
          auto *ipc = CHI_IPC;
          auto shm = ipc->AllocateBuffer(size);
          if (shm.IsNull()) { pk.pack("{}"); } else {
          auto get_future = WRP_CTE_CLIENT->AsyncGetBlob(
              tag_id, blob_name, 0, size, 0, hipc::ShmPtr<>(shm.shm_));
          co_await get_future;
          pk.pack(std::string(reinterpret_cast<char*>(shm.ptr_), size));
          ipc->FreeBuffer(shm); }
        } else {
          pk.pack("{}");
        }
      } catch (...) {
        pk.pack("{}");
      }
    } else {
      pk.pack("{}");
    }
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0);
    co_return;
  }

  // 5. Recovery event handlers
  if (query_str.rfind("store_recovery_event://", 0) == 0) {
    std::string json_payload = query_str.substr(23);
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    try {
      auto payload_json = json::parse(json_payload);
      std::string event_id = payload_json.value("event_id", "");
      std::string target_session_id = payload_json.value("target_session_id", "");
      if (!event_id.empty() && !target_session_id.empty()) {
        std::string tag_name = "Recovery_" + target_session_id;
        auto tag_future = WRP_CTE_CLIENT->AsyncGetOrCreateTag(tag_name);
        co_await tag_future;
        auto tag_id = tag_future->tag_id_;
        auto *ipc = CHI_IPC;
        size_t payload_size = json_payload.size();
        auto shm = ipc->AllocateBuffer(payload_size);
        if (!shm.IsNull()) {
          memcpy(shm.ptr_, json_payload.data(), payload_size);
          auto put_future = WRP_CTE_CLIENT->AsyncPutBlob(
              tag_id, event_id, 0, payload_size, hipc::ShmPtr<>(shm.shm_));
          co_await put_future;
          ipc->FreeBuffer(shm);
          pk.pack(event_id);
        } else {
          pk.pack("");
        }
      } else {
        pk.pack("");
      }
    } catch (...) {
      pk.pack("");
    }
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0);
    co_return;
  }

  if (query_str.rfind("query_recovery_events://", 0) == 0) {
    std::string session_id = query_str.substr(24);
    std::string tag_name = "Recovery_" + session_id;
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    try {
      auto tag_future = WRP_CTE_CLIENT->AsyncGetOrCreateTag(tag_name);
      co_await tag_future;
      auto tag_id = tag_future->tag_id_;
      auto blobs_future = WRP_CTE_CLIENT->AsyncGetContainedBlobs(tag_id);
      co_await blobs_future;
      auto& blobs = blobs_future->blob_names_;
      auto *ipc = CHI_IPC;
      pk.pack_array(static_cast<uint32_t>(blobs.size()));
      for (const auto& bname : blobs) {
        auto size_future = WRP_CTE_CLIENT->AsyncGetBlobSize(tag_id, bname);
        co_await size_future;
        auto size = size_future->size_;
        if (size == 0) {
          pk.pack_array(2); pk.pack(bname); pk.pack("");
          continue;
        }
        auto shm = ipc->AllocateBuffer(size);
        if (shm.IsNull()) {
          pk.pack_array(2); pk.pack(bname); pk.pack("");
          continue;
        }
        auto get_future = WRP_CTE_CLIENT->AsyncGetBlob(
            tag_id, bname, 0, size, 0, hipc::ShmPtr<>(shm.shm_));
        co_await get_future;
        std::string json_str(reinterpret_cast<char*>(shm.ptr_), size);
        pk.pack_array(2); pk.pack(bname); pk.pack(json_str);
        ipc->FreeBuffer(shm);
      }
    } catch (...) {
      pk.pack_array(0);
    }
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0);
    co_return;
  }

  if (query_str.rfind("ack_recovery_event://", 0) == 0) {
    std::string body = query_str.substr(21);
    auto slash = body.find('/');
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    if (slash != std::string::npos) {
      std::string session_id = body.substr(0, slash);
      std::string blob_name = body.substr(slash + 1);
      std::string tag_name = "Recovery_" + session_id;
      try {
        auto tag_future = WRP_CTE_CLIENT->AsyncGetOrCreateTag(tag_name);
        co_await tag_future;
        auto tag_id = tag_future->tag_id_;
        auto size_future = WRP_CTE_CLIENT->AsyncGetBlobSize(tag_id, blob_name);
        co_await size_future;
        auto size = size_future->size_;
        std::string updated_json;
        if (size > 0) {
          auto *ipc = CHI_IPC;
          auto shm = ipc->AllocateBuffer(size);
          if (!shm.IsNull()) {
            auto get_future = WRP_CTE_CLIENT->AsyncGetBlob(
                tag_id, blob_name, 0, size, 0, hipc::ShmPtr<>(shm.shm_));
            co_await get_future;
            std::string json_str(reinterpret_cast<char*>(shm.ptr_), size);
            ipc->FreeBuffer(shm);
            try {
              auto evt_json = json::parse(json_str);
              evt_json["acknowledged"] = true;
              updated_json = evt_json.dump();
            } catch (...) {
              updated_json = json_str;
            }
          }
        }
        if (!updated_json.empty()) {
          auto *ipc = CHI_IPC;
          size_t new_size = updated_json.size();
          auto shm = ipc->AllocateBuffer(new_size);
          if (!shm.IsNull()) {
            memcpy(shm.ptr_, updated_json.data(), new_size);
            auto put_future = WRP_CTE_CLIENT->AsyncPutBlob(
                tag_id, blob_name, 0, new_size, hipc::ShmPtr<>(shm.shm_));
            co_await put_future;
            ipc->FreeBuffer(shm);
            pk.pack("ok");
          } else {
            pk.pack("error");
          }
        } else {
          pk.pack("error");
        }
      } catch (...) {
        pk.pack("error");
      }
    } else {
      pk.pack("error");
    }
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0);
    co_return;
  }

  // 6. Logged checkpoint handlers
  if (query_str.rfind("store_lg_checkpoint://", 0) == 0) {
    std::string body = query_str.substr(22);
    auto slash = body.find('/');
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    if (slash != std::string::npos) {
      std::string tag_name = body.substr(0, slash);
      std::string json_payload = body.substr(slash + 1);
      try {
        auto tag_future = WRP_CTE_CLIENT->AsyncGetOrCreateTag(tag_name);
        co_await tag_future;
        auto tag_id = tag_future->tag_id_;
        auto blobs_future = WRP_CTE_CLIENT->AsyncGetContainedBlobs(tag_id);
        co_await blobs_future;
        auto& blobs = blobs_future->blob_names_;
        uint64_t next_seq = blobs.size() + 1;
        char blob_buf[16];
        snprintf(blob_buf, sizeof(blob_buf), "%010lu",
                 static_cast<unsigned long>(next_seq));
        std::string blob_name(blob_buf);
        auto *ipc = CHI_IPC;
        size_t payload_size = json_payload.size();
        auto shm = ipc->AllocateBuffer(payload_size);
        if (!shm.IsNull()) {
          memcpy(shm.ptr_, json_payload.data(), payload_size);
          auto put_future = WRP_CTE_CLIENT->AsyncPutBlob(
              tag_id, blob_name, 0, payload_size, hipc::ShmPtr<>(shm.shm_));
          co_await put_future;
          ipc->FreeBuffer(shm);
          pk.pack(blob_name);
        } else {
          pk.pack("");
        }
      } catch (...) {
        pk.pack("");
      }
    } else {
      pk.pack("");
    }
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0);
    co_return;
  }

  if (query_str.rfind("query_lg_checkpoints://", 0) == 0) {
    std::string tag_name = query_str.substr(23);
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    try {
      auto tag_future = WRP_CTE_CLIENT->AsyncGetOrCreateTag(tag_name);
      co_await tag_future;
      auto tag_id = tag_future->tag_id_;
      auto blobs_future = WRP_CTE_CLIENT->AsyncGetContainedBlobs(tag_id);
      co_await blobs_future;
      auto& blobs = blobs_future->blob_names_;
      auto *ipc = CHI_IPC;
      pk.pack_array(static_cast<uint32_t>(blobs.size()));
      for (const auto& bname : blobs) {
        auto size_future = WRP_CTE_CLIENT->AsyncGetBlobSize(tag_id, bname);
        co_await size_future;
        auto size = size_future->size_;
        if (size == 0) {
          pk.pack_array(2); pk.pack(bname); pk.pack("");
          continue;
        }
        auto shm = ipc->AllocateBuffer(size);
        if (shm.IsNull()) {
          pk.pack_array(2); pk.pack(bname); pk.pack("");
          continue;
        }
        auto get_future = WRP_CTE_CLIENT->AsyncGetBlob(
            tag_id, bname, 0, size, 0, hipc::ShmPtr<>(shm.shm_));
        co_await get_future;
        std::string json_str(reinterpret_cast<char*>(shm.ptr_), size);
        pk.pack_array(2); pk.pack(bname); pk.pack(json_str);
        ipc->FreeBuffer(shm);
      }
    } catch (...) {
      pk.pack_array(0);
    }
    task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
    task->SetReturnCode(0);
    co_return;
  }

  task->SetReturnCode(0);
  co_return;
}

// ── ForwardHttp (runs on I/O worker) ────────────────────────────────────

chi::TaskResume Runtime::ForwardHttp(hipc::FullPtr<ForwardHttpTask> task,
                                     chi::RunContext& rctx) {
  (void)rctx;
  std::string query_json(task->query_json_.str());
  auto query = json::parse(query_json);
  std::string session_id = query.value("session_id", "");
  std::string scenario_id = query.value("scenario_id", "");
  std::string agent_host = query.value("agent_host", "");
  std::string provider_name = query.value("provider", "");
  std::string path = query.value("path", "/");
  std::string headers_str = query.contains("headers")
      ? query["headers"].dump() : "{}";
  std::string body = query.value("body", "");

  auto provider = ProviderFromString(provider_name);
  std::string upstream_url = SelectUpstream(provider);

  if (upstream_url.empty()) {
    msgpack::sbuffer sbuf;
    msgpack::packer<msgpack::sbuffer> pk(sbuf);
    pk.pack_map(3);
    pk.pack("status"); pk.pack(502);
    pk.pack("headers"); pk.pack("{}");
    pk.pack("body");
    pk.pack(std::string(R"({"error":"unknown provider: )" +
                        provider_name + R"("})"));
    task->response_msgpack_ = std::string(sbuf.data(), sbuf.size());
    task->record_json_ = "";
    co_return;
  }

  total_requests_.fetch_add(1, std::memory_order_relaxed);

  // Blocking HTTP call — OK, we're on an I/O worker, not Worker 0
  int resp_status = 502;
  std::string resp_headers, resp_body;
  double latency_ms = 0;
  ForwardDirect(upstream_url, path, headers_str, body,
                resp_status, resp_headers, resp_body, latency_ms);

  HLOG(kInfo, "ForwardHttp: session={} provider={} status={} latency={}ms",
       session_id, provider_name, resp_status,
       static_cast<int>(latency_ms));

  // Build interaction record for tracker storage — timed separately from LLM call.
  // Store *every* response (incl. 4xx/5xx) — error observability is the point of
  // the tracker. BuildInteractionRecord skips body parsing for non-2xx responses
  // and surfaces the error text instead.
  std::string record_json;
  if (resp_status >= 100 && resp_status < 600) {
    try {
      const bool logging = overhead_logging_.load(std::memory_order_relaxed);
      auto record_start = logging ? std::chrono::steady_clock::now()
                                  : std::chrono::steady_clock::time_point{};
      record_json = BuildInteractionRecord(
          session_id, scenario_id, agent_host, provider, path, headers_str, body,
          resp_status, resp_headers, resp_body, latency_ms);
      if (logging && !record_json.empty()) {
        auto record_end = std::chrono::steady_clock::now();
        double proxy_overhead_ms = std::chrono::duration<double, std::milli>(
            record_end - record_start).count();
        uint64_t proxy_overhead_us = static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::microseconds>(
                record_end - record_start).count());
        total_proxy_overhead_us_.fetch_add(proxy_overhead_us,
                                           std::memory_order_relaxed);
        // Inject proxy_overhead_ms into the record JSON so it is persisted in CTE
        try {
          auto rec = json::parse(record_json);
          if (rec.contains("metrics")) {
            rec["metrics"]["proxy_overhead_ms"] = proxy_overhead_ms;
          }
          record_json = rec.dump();
        } catch (...) {}
      }
    } catch (...) {
      HLOG(kWarning, "Failed to build interaction record for session={}", session_id);
    }
  }

  // Pack response as msgpack
  msgpack::sbuffer sbuf;
  msgpack::packer<msgpack::sbuffer> pk(sbuf);
  pk.pack_map(3);
  pk.pack("status"); pk.pack(resp_status);
  pk.pack("headers"); pk.pack(resp_headers);
  pk.pack("body"); pk.pack(resp_body);
  task->response_msgpack_ = std::string(sbuf.data(), sbuf.size());
  task->record_json_ = record_json;
  co_return;
}

// ── GetTaskStats ────────────────────────────────────────────────────────

chi::TaskStat Runtime::GetTaskStats(chi::u32 method_id) const {
  // Route ForwardHttp to I/O workers (io_size >= 4096 triggers I/O lane)
  if (method_id == Method::kForwardHttp) {
    chi::TaskStat stat;
    stat.io_size_ = 8192;
    return stat;
  }
  return chi::TaskStat();
}

// ── HandleDispatchStats ─────────────────────────────────────────────────

void Runtime::HandleDispatchStats(hipc::FullPtr<MonitorTask>& task) {
  auto now = std::chrono::steady_clock::now();
  auto uptime_s = std::chrono::duration_cast<std::chrono::seconds>(
      now - start_time_).count();

  // NOTE: Cannot query tracker inline (blocking Wait() would deadlock
  // when called from a Chimaera worker thread via inline Monitor dispatch).
  // active_sessions is reported as 0 for now — the dashboard can query
  // list_sessions separately and count.
  uint64_t active_sessions = 0;
  uint64_t total_requests = total_requests_.load(std::memory_order_relaxed);
  uint64_t proxy_overhead_us = total_proxy_overhead_us_.load(std::memory_order_relaxed);
  uint64_t pipeline_overhead_us = total_pipeline_overhead_us_.load(std::memory_order_relaxed);

  // Average overheads (0 if no requests yet)
  double avg_proxy_overhead_ms = total_requests > 0
      ? static_cast<double>(proxy_overhead_us) / total_requests / 1000.0 : 0.0;
  double avg_pipeline_overhead_ms = total_requests > 0
      ? static_cast<double>(pipeline_overhead_us) / total_requests / 1000.0 : 0.0;

  msgpack::sbuffer sbuf;
  msgpack::packer<msgpack::sbuffer> pk(sbuf);
  pk.pack_map(7);
  pk.pack("total_requests"); pk.pack(total_requests);
  pk.pack("active_sessions"); pk.pack(active_sessions);
  pk.pack("uptime_seconds"); pk.pack(static_cast<uint64_t>(uptime_s));
  pk.pack("total_proxy_overhead_us"); pk.pack(proxy_overhead_us);
  pk.pack("total_pipeline_overhead_us"); pk.pack(pipeline_overhead_us);
  pk.pack("avg_proxy_overhead_ms"); pk.pack(avg_proxy_overhead_ms);
  pk.pack("avg_pipeline_overhead_ms"); pk.pack(avg_pipeline_overhead_ms);
  task->results_[container_id_] = std::string(sbuf.data(), sbuf.size());
}

// ── Destroy / GetWorkRemaining ──────────────────────────────────────────

chi::TaskResume Runtime::Destroy(hipc::FullPtr<DestroyTask> task,
                                 chi::RunContext& rctx) {
  HLOG(kInfo, "DTProvenance proxy shutting down");
  tracker_client_.reset();
  tracker_initialized_ = false;
  (void)task;
  (void)rctx;
  co_return;
}

chi::u64 Runtime::GetWorkRemaining() const {
  return 0;
}

}  // namespace dt_provenance::proxy

CHI_TASK_CC(dt_provenance::proxy::Runtime)
