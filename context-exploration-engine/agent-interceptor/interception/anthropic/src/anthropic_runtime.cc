#include "dt_provenance/interception/anthropic/anthropic_runtime.h"

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>

#define CPPHTTPLIB_OPENSSL_SUPPORT
#include <httplib.h>

#include "dt_provenance/protocol/anthropic_parser.h"
#include "dt_provenance/protocol/cost_estimator.h"
#include "dt_provenance/protocol/interaction.h"
#include "dt_provenance/protocol/stream_reassembly.h"
#include "dt_provenance/tracker/tracker_client.h"

namespace dt_provenance::interception::anthropic {

namespace {

// Parsed HTTP(S) proxy settings derived from process env vars. Follows the
// de-facto `HTTPS_PROXY` / `HTTP_PROXY` convention (with lowercase fallbacks)
// and an optional `NO_PROXY` bypass list. We only support the CONNECT-target
// form `[scheme://][user:pass@]host:port`; the scheme is stripped because
// cpp-httplib's set_proxy takes host/port directly.
struct ProxySettings {
  std::string host;
  int port = 0;
  std::string user;
  std::string pass;
  std::vector<std::string> no_proxy_hosts;
  bool valid = false;
};

inline const char* GetEnvFirst(const char* a, const char* b) {
  const char* v = std::getenv(a);
  if (v && *v) return v;
  v = std::getenv(b);
  return (v && *v) ? v : nullptr;
}

ProxySettings ReadProxyFromEnv(bool ssl) {
  ProxySettings out;
  const char* url = ssl ? GetEnvFirst("HTTPS_PROXY", "https_proxy")
                        : GetEnvFirst("HTTP_PROXY", "http_proxy");
  if (!url) return out;

  std::string s(url);
  if (auto scheme = s.find("://"); scheme != std::string::npos) {
    s.erase(0, scheme + 3);
  }
  if (auto at = s.find('@'); at != std::string::npos) {
    std::string creds = s.substr(0, at);
    s.erase(0, at + 1);
    if (auto c = creds.find(':'); c != std::string::npos) {
      out.user = creds.substr(0, c);
      out.pass = creds.substr(c + 1);
    } else {
      out.user = std::move(creds);
    }
  }
  // Trim a trailing path segment if the env var included one.
  if (auto slash = s.find('/'); slash != std::string::npos) {
    s.erase(slash);
  }
  auto colon = s.find(':');
  if (colon == std::string::npos) return out;
  out.host = s.substr(0, colon);
  try {
    out.port = std::stoi(s.substr(colon + 1));
  } catch (...) {
    return out;
  }

  if (const char* np = GetEnvFirst("NO_PROXY", "no_proxy")) {
    std::string np_str(np);
    size_t start = 0;
    while (start <= np_str.size()) {
      auto comma = np_str.find(',', start);
      auto end = (comma == std::string::npos) ? np_str.size() : comma;
      std::string part = np_str.substr(start, end - start);
      while (!part.empty() && (part.front() == ' ' || part.front() == '\t')) {
        part.erase(part.begin());
      }
      while (!part.empty() && (part.back() == ' ' || part.back() == '\t')) {
        part.pop_back();
      }
      if (!part.empty()) out.no_proxy_hosts.push_back(std::move(part));
      if (comma == std::string::npos) break;
      start = comma + 1;
    }
  }

  out.valid = !out.host.empty() && out.port > 0;
  return out;
}

bool HostMatchesNoProxy(const std::string& host,
                        const std::vector<std::string>& list) {
  for (const auto& pat : list) {
    if (pat == "*") return true;
    if (host == pat) return true;
    // Suffix match: ".example.com" matches "x.example.com".
    if (!pat.empty() && pat.front() == '.' && host.size() >= pat.size() &&
        host.compare(host.size() - pat.size(), pat.size(), pat) == 0) {
      return true;
    }
    // Conventional localhost alias.
    if (pat == "localhost" && (host == "localhost" || host == "127.0.0.1")) {
      return true;
    }
  }
  return false;
}

template <typename Cli>
void ApplyProxyIfNeeded(Cli& cli, const std::string& upstream_host, bool ssl) {
  auto ps = ReadProxyFromEnv(ssl);
  if (!ps.valid) return;
  if (HostMatchesNoProxy(upstream_host, ps.no_proxy_hosts)) return;
  cli.set_proxy(ps.host, ps.port);
  if (!ps.user.empty()) cli.set_proxy_basic_auth(ps.user, ps.pass);
}

// ISO-8601 UTC timestamp (millisecond precision). Populates
// InteractionRecord::timestamp so the visualizer's timeline has a stable
// sort key — previously every interaction got the default empty string,
// which made the workspace timeline render blank even with real traffic.
std::string IsoNowUtc() {
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

}  // namespace

Runtime::~Runtime() = default;

using json = nlohmann::ordered_json;
using namespace dt_provenance::protocol;

/**
 * Parse a URL into host, port, and ssl flag
 */
static void ParseUrl(const std::string& url, std::string& host, int& port,
                     bool& ssl) {
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

  // Check for port in host
  auto colon = host.find(':');
  if (colon != std::string::npos) {
    port = std::stoi(host.substr(colon + 1));
    host = host.substr(0, colon);
  }

  // Strip trailing slash
  if (!host.empty() && host.back() == '/') {
    host.pop_back();
  }
}

chi::TaskResume Runtime::Create(hipc::FullPtr<CreateTask> task,
                                chi::RunContext& rctx) {
  auto params = task->GetParams();
  std::string url(params.upstream_base_url_.str());

  ParseUrl(url, upstream_host_, upstream_port_, upstream_ssl_);

  HLOG(kInfo, "Anthropic interception ChiMod created: upstream={}:{} ssl={}",
       upstream_host_, upstream_port_, upstream_ssl_);
  co_return;
}

chi::TaskResume Runtime::InterceptAndForward(
    hipc::FullPtr<InterceptAndForwardTask> task, chi::RunContext& rctx) {
  HLOG(kInfo, "Anthropic InterceptAndForward: COROUTINE STARTED");
  active_requests_.fetch_add(1);
  auto start = std::chrono::steady_clock::now();

  // Extract task fields
  std::string session_id(task->session_id_.str());
  std::string path(task->path_.str());
  std::string headers_json_str(task->headers_json_.str());
  std::string request_body(task->request_body_.str());

  // Parse headers
  json request_headers;
  try {
    request_headers = json::parse(headers_json_str);
  } catch (const json::parse_error&) {
    request_headers = json::object();
  }

  // 1. Create httplib client for this request
  httplib::Headers hdr;
  for (auto& [k, v] : request_headers.items()) {
    if (v.is_string()) {
      hdr.emplace(k, v.get<std::string>());
    }
  }

  std::string response_body;
  int response_status = 502;
  httplib::Headers response_headers;

  HLOG(kInfo, "Anthropic: creating SSL client to {}:{}", upstream_host_,
       upstream_port_);
  if (upstream_ssl_) {
    httplib::SSLClient cli(upstream_host_, upstream_port_);
    cli.set_connection_timeout(30);
    cli.set_read_timeout(300);  // LLM responses can be slow
    cli.enable_server_certificate_verification(false);  // TODO: proper cert handling
    // On restricted networks (e.g. HPC clusters with only a Squid egress),
    // the only path to the upstream is through a corporate proxy declared
    // via HTTPS_PROXY/HTTP_PROXY. Honor those so the interceptor works in
    // the same places curl/pip/git already do.
    ApplyProxyIfNeeded(cli, upstream_host_, true);

    HLOG(kInfo, "Anthropic: sending POST to {}", path);
    auto res = cli.Post(path, hdr, request_body, "application/json");
    if (res) {
      response_status = res->status;
      response_body = res->body;
      response_headers = res->headers;
    }
  } else {
    httplib::Client cli(upstream_host_, upstream_port_);
    cli.set_connection_timeout(30);
    cli.set_read_timeout(300);
    ApplyProxyIfNeeded(cli, upstream_host_, false);

    auto res = cli.Post(path, hdr, request_body, "application/json");
    if (res) {
      response_status = res->status;
      response_body = res->body;
      response_headers = res->headers;
    }
  }

  HLOG(kInfo, "Anthropic: HTTP request completed, status={}", response_status);
  auto end = std::chrono::steady_clock::now();
  double latency_ms = std::chrono::duration<double, std::milli>(end - start).count();

  // 2. Set OUT fields so the proxy can return the response immediately
  task->response_status_ = response_status;
  task->latency_ms_ = latency_ms;
  task->ttft_ms_ = latency_ms;  // For non-streaming; TODO: measure TTFT for SSE

  // Serialize response headers (normalize keys to lowercase for consistent lookup)
  json resp_hdrs_json = json::object();
  for (const auto& [k, v] : response_headers) {
    std::string lower_k = k;
    std::transform(lower_k.begin(), lower_k.end(), lower_k.begin(), ::tolower);
    resp_hdrs_json[lower_k] = v;
  }
  task->response_headers_json_ = resp_hdrs_json.dump();
  task->response_body_ = response_body;

  // 3. Parse interaction asynchronously (still in this coroutine, but after
  //    setting OUT fields so the proxy can resume)
  if (response_status >= 200 && response_status < 300) {
    InteractionRecord record;
    record.session_id = session_id;
    record.provider = Provider::kAnthropic;
    // Wall-clock timestamp at record-build time (best proxy for "when the
    // turn happened" given we don't carry the request-arrival time through
    // the task coroutine). Required by the workspace timeline.
    record.timestamp = IsoNowUtc();
    record.request.method = "POST";
    record.request.path = path;
    record.request.headers = request_headers;

    // Parse request
    try {
      auto req_body = json::parse(request_body);
      AnthropicParser::ParseRequest(req_body, record);
    } catch (const json::parse_error&) {}

    // Detect streaming response by content-type
    bool is_sse = false;
    if (resp_hdrs_json.contains("content-type")) {
      std::string ct = resp_hdrs_json["content-type"].get<std::string>();
      is_sse = ct.find("text/event-stream") != std::string::npos;
    }

    // Parse response
    if (is_sse) {
      record.response.is_streaming = true;
      auto chunks = ReassembleSSE(response_body);
      for (const auto& chunk : chunks) {
        AnthropicParser::ParseStreamChunk(chunk, record);
      }
    } else {
      record.response.is_streaming = false;
      try {
        auto resp_body = json::parse(response_body);
        AnthropicParser::ParseResponse(resp_body, record);
      } catch (const json::parse_error&) {}
    }

    // Estimate cost
    TokenUsage usage;
    usage.input_tokens = record.metrics.input_tokens;
    usage.output_tokens = record.metrics.output_tokens;
    usage.cache_creation_tokens = record.metrics.cache_creation_tokens;
    usage.cache_read_tokens = record.metrics.cache_read_tokens;
    auto cost = CostEstimator::Estimate(Provider::kAnthropic, record.model, usage);
    record.metrics.cost_usd = cost.total_cost;
    record.metrics.total_latency_ms = latency_ms;
    record.metrics.time_to_first_token_ms = latency_ms;  // TODO

    record.response.status_code = response_status;

    // 4. Dispatch to Tracker
    HLOG(kInfo,
         "Anthropic interaction captured: session={} model={} "
         "in_tokens={} out_tokens={} latency={}ms",
         session_id, record.model, record.metrics.input_tokens,
         record.metrics.output_tokens, static_cast<int>(latency_ms));

    if (!tracker_initialized_) {
      chi::PoolId pool = CHI_POOL_MANAGER->FindPoolByName("dt_tracker_pool");
      if (!pool.IsNull()) {
        tracker_client_ = std::make_unique<dt_provenance::tracker::Client>(pool);
        tracker_initialized_ = true;
      }
    }
    if (tracker_initialized_) {
      std::string record_json = record.ToJson().dump();
      auto f = tracker_client_->AsyncStoreInteraction(
          chi::PoolQuery::Local(), record_json);
      f.Wait();
    }
  }

  active_requests_.fetch_sub(1);
  co_return;
}

chi::TaskResume Runtime::Monitor(hipc::FullPtr<MonitorTask> task,
                                 chi::RunContext& rctx) {
  (void)task;
  (void)rctx;
  co_return;
}

chi::TaskResume Runtime::Destroy(hipc::FullPtr<DestroyTask> task,
                                 chi::RunContext& rctx) {
  HLOG(kInfo, "Anthropic interception ChiMod destroyed");
  (void)task;
  (void)rctx;
  co_return;
}

chi::u64 Runtime::GetWorkRemaining() const {
  return active_requests_.load();
}

}  // namespace dt_provenance::interception::anthropic

CHI_TASK_CC(dt_provenance::interception::anthropic::Runtime)
