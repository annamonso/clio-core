"""Wrapper around chimaera_runtime_ext for the visualizer."""

import concurrent.futures
import os
import socket
import threading

# The dashboard client should never block retrying a dead runtime.
# 0 = fail immediately; the dashboard relies on TCP liveness checks instead.
os.environ.setdefault("CHI_CLIENT_RETRY_TIMEOUT", "0")
os.environ.setdefault("CHI_CLIENT_TRY_NEW_SERVERS", "16")

try:
    import msgpack
except ImportError:
    msgpack = None

# Default timeout (seconds) for async_monitor calls.  Broadcasts that include
# dead nodes can block for 30+ seconds waiting on retries, so we cap them.
_MONITOR_TIMEOUT = 10

_lock = threading.Lock()
_chi = None
_init_done = False

# Single shared worker thread for ALL C++ client calls.
# The C++ IPC layer is not thread-safe (ReconnectToNewHost mutates shared
# transport state), so we must serialize all calls.  The GIL is released
# inside task.wait() so the main thread can still enforce timeouts and
# serve Flask requests while the worker blocks in C++.
_chi_worker = concurrent.futures.ThreadPoolExecutor(max_workers=1)


def _ensure_init():
    """Lazy-initialize the Chimaera client connection."""
    global _chi, _init_done
    if _init_done:
        return
    with _lock:
        if _init_done:
            return
        import chimaera_runtime_ext as chi
        _chi = chi
        # 0 = kClient — pass a plain int to avoid any nanobind enum objects
        ok = chi.chimaera_init(0)
        if not ok:
            raise RuntimeError("chimaera_init(kClient) failed -- is the runtime running?")
        _init_done = True


def _decode_results(results):
    """Decode a {container_id: bytes} dict into {container_id: decoded_data}."""
    decoded = {}
    for cid, blob in results.items():
        if msgpack is not None and isinstance(blob, (bytes, bytearray)):
            try:
                decoded[str(cid)] = msgpack.unpackb(blob, raw=False)
            except Exception:
                decoded[str(cid)] = blob
        else:
            decoded[str(cid)] = blob
    return decoded


def _do_monitor(pool_query, query, timeout):
    """Run async_monitor + wait in the calling thread (used by _monitor)."""
    task = _chi.async_monitor(pool_query, query)
    results = task.wait(timeout)
    return results


def _monitor(pool_query, query, timeout=_MONITOR_TIMEOUT):
    """Execute an async_monitor call with a timeout.

    The timeout is passed to both the C++ Wait() (so the worker thread
    is freed promptly) and the Python future.result() (so the caller
    is not blocked longer than necessary).
    """
    _ensure_init()
    future = _chi_worker.submit(_do_monitor, pool_query, query, timeout)
    try:
        results = future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(
            f"Monitor({pool_query!r}, {query!r}) timed out after {timeout}s"
        )
    return _decode_results(results)


def is_connected():
    """Return True if the client has been initialized."""
    return _init_done



def reinit():
    """Tear down and reset the C++ client so the next call reconnects.

    Call this after the local runtime has been restarted so the client
    picks up the fresh process instead of using stale state.
    """
    global _init_done, _chi
    with _lock:
        if _init_done and _chi is not None:
            try:
                _chi.chimaera_finalize()
            except Exception:
                pass
        _init_done = False
        _chi = None


def get_worker_stats():
    """Query worker_stats from the admin pool (local node)."""
    return _monitor("local", "worker_stats")


def get_pool_worker_stats(pool_id_str, routing="local"):
    """Query worker_stats for a specific pool via pool_stats:// URI."""
    return _monitor("local", f"pool_stats://{pool_id_str}:{routing}:worker_stats")


def get_status():
    """Query general status from the admin pool."""
    return _monitor("local", "status")


def get_system_stats(pool_query="local", min_event_id=0):
    """Query system_stats from the admin pool."""
    return _monitor(pool_query, f"system_stats:{min_event_id}")


def get_system_stats_all(min_event_id=0):
    """Broadcast system_stats to all nodes (each self-identifies via hostname/ip/node_id)."""
    return _monitor("broadcast", f"system_stats:{min_event_id}")


def check_nodes_alive(ip_list, port=9413, timeout=1):
    """Check which nodes are alive by attempting a TCP connection to their RPC port.

    Returns a set of indices (matching ip_list positions) that are alive.
    This avoids the C++ runtime's IPC layer which blocks on dead nodes.
    """
    alive = set()

    def _check_one(idx, ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((ip, port))
            s.close()
            return idx
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(len(ip_list), 1)) as pool:
        futures = [pool.submit(_check_one, i, ip) for i, ip in enumerate(ip_list)]
        for f in concurrent.futures.as_completed(futures, timeout=timeout + 2):
            try:
                idx = f.result()
                if idx is not None:
                    alive.add(idx)
            except Exception:
                pass

    return alive


def get_system_stats_per_node(node_ids, min_event_id=0, timeout=3):
    """Query system_stats for each node sequentially.

    Returns {node_id: entry_dict} for nodes that responded, skipping
    dead nodes instead of blocking the whole request.

    Queries are serialized through the shared _chi_worker to avoid
    concurrent access to the C++ IPC layer.  The topology endpoint
    already filters to alive-only nodes via TCP checks, so the
    sequential delay is minimal.
    """
    _ensure_init()
    results = {}

    for node_id in node_ids:
        try:
            raw = _monitor(f"physical:{node_id}", f"system_stats:{min_event_id}", timeout=timeout)
            latest = None
            for cid, entries in raw.items():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            latest = entry
            if latest is not None:
                results[node_id] = latest
        except Exception:
            pass

    return results


def get_bdev_stats(pool_query="local"):
    """Query bdev_stats from the admin pool."""
    return _monitor(pool_query, "bdev_stats")


def get_worker_stats_for_node(node_id):
    """Query worker_stats for a specific node."""
    return _monitor(f"physical:{node_id}", "worker_stats")


def get_system_stats_for_node(node_id, min_event_id=0):
    """Query system_stats for a specific node."""
    return _monitor(f"physical:{node_id}", f"system_stats:{min_event_id}")


def get_bdev_stats_for_node(node_id):
    """Query bdev_stats for a specific node."""
    return _monitor(f"physical:{node_id}", "bdev_stats")


def get_container_stats(pool_query="local"):
    """Query container_stats from the admin pool."""
    return _monitor(pool_query, "container_stats")


def get_container_stats_for_node(node_id):
    """Query container_stats for a specific node."""
    return _monitor(f"physical:{node_id}", "container_stats")


def get_host_info(node_id):
    """Query host info (hostname, ip_address, node_id) for a specific node."""
    decoded = _monitor(f"physical:{node_id}", "get_host_info")
    for entry in decoded.values():
        if isinstance(entry, dict):
            return entry
    return {}


def _do_stop_runtime(pool_query, grace_period_ms):
    """Run stop_runtime on the shared worker thread."""
    _chi.stop_runtime(pool_query, grace_period_ms)


def shutdown_node(node_id, grace_period_ms=5000):
    """Shutdown a node via AsyncStopRuntime through the C++ client.

    Sends the same task the C++ unit tests use — no SSH required.
    Fire-and-forget: the target runtime dies before it can reply.
    Serialized through _chi_worker to avoid concurrent C++ access.
    """
    _ensure_init()
    pool_query = f"physical:{node_id}"
    try:
        future = _chi_worker.submit(_do_stop_runtime, pool_query, grace_period_ms)
        future.result(timeout=5)
    except Exception as exc:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "success": True,
        "returncode": 0,
        "stdout": f"StopRuntime sent to node {node_id}",
        "stderr": "",
    }


def restart_node(ip_address, port=9413):
    """Restart a node's Chimaera runtime (non-blocking).

    Assumes the runtime is already dead (shutdown_node was called first).
    Launches ``chimaera runtime restart`` (WAL replay) so the node rejoins
    the existing cluster. Returns immediately — the dashboard's topology
    polling (TCP-based) will detect when the node comes back.
    """
    import os
    import subprocess

    local_ip = os.environ.get("NODE_IP", "")
    is_local = (ip_address == local_ip)

    print(f"[restart_node] Starting restart for {ip_address}:{port} "
          f"(local={is_local})", flush=True)

    if is_local:
        print("[restart_node] Launching local runtime via Popen", flush=True)
        try:
            subprocess.Popen(
                ["chimaera", "runtime", "restart"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:
            print(f"[restart_node] Popen failed: {exc}", flush=True)
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": f"Failed to launch runtime: {exc}",
            }
    else:
        env_parts = []
        for var in ("PATH", "LD_LIBRARY_PATH",
                    "CHI_SERVER_CONF", "CHI_NUM_CONTAINERS",
                    "CONTAINER_HOSTFILE"):
            val = os.environ.get(var)
            if val:
                env_parts.append(f"{var}={val}")
        env_str = ("export " + " ".join(env_parts) + " && ") if env_parts else ""
        remote_cmd = (
            f"{env_str}"
            f"nohup setsid chimaera runtime restart "
            f"</dev/null >/dev/null 2>&1 & disown; exit 0"
        )
        cmd = [
            "ssh", "-T", "-n",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=5",
            ip_address,
            remote_cmd,
        ]
        print(f"[restart_node] Starting via SSH: {' '.join(cmd)}", flush=True)
        try:
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as exc:
            print(f"[restart_node] SSH exception: {exc}", flush=True)
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": f"SSH start command failed: {exc}",
            }

    print("[restart_node] Runtime launch initiated — returning immediately",
          flush=True)
    return {
        "success": True,
        "returncode": 0,
        "stdout": "Restart initiated; topology polling will detect when ready",
        "stderr": "",
    }


def forward_llm_request(
    session_id,
    provider,
    path,
    headers,
    body,
    timeout=300,
    scenario_id="",
    agent_host="",
):
    """Forward an LLM request via the proxy ChiMod's Monitor handler.

    scenario_id groups independent peer agents into one multi-agent scenario.
    agent_host is the hostname of the agent that emitted the request (may
    differ from the interceptor's own host when agents run on separate nodes).
    """
    import json as _json
    query = _json.dumps({
        "action": "forward",
        "session_id": session_id,
        "scenario_id": scenario_id,
        "agent_host": agent_host,
        "provider": provider,
        "path": path,
        "headers": headers,
        "body": body,
    })
    return _monitor("local", f"pool_stats://800.0:local:{query}", timeout=timeout)


def get_dispatch_stats():
    """Query dispatch stats from the proxy ChiMod (pool 800.0)."""
    return _monitor("local", "pool_stats://800.0:local:dispatch_stats")


def get_proxy_sessions():
    """Query session list from the proxy ChiMod (delegates to tracker)."""
    return _monitor("local", "pool_stats://800.0:local:list_sessions")


def get_proxy_session(session_id):
    """Query session interactions via proxy ChiMod."""
    return _monitor("local", f"pool_stats://800.0:local:query_session://{session_id}")


def get_proxy_graph(session_id, since=0):
    """Query context graph via proxy ChiMod."""
    q = f"query_graph://{session_id}"
    if since:
        q += f"?since={since}"
    return _monitor("local", f"pool_stats://800.0:local:{q}")


def get_sessions():
    """Query list_sessions via the proxy ChiMod (pool 800.0)."""
    return _monitor("local", "pool_stats://800.0:local:list_sessions")


def get_session_interactions(session_id):
    """Query all interactions for a session via the proxy ChiMod (pool 800.0)."""
    return _monitor("local", f"pool_stats://800.0:local:query_session://{session_id}")


def get_interaction(session_id, seq_id):
    """Query a single interaction via the proxy ChiMod (pool 800.0)."""
    return _monitor("local", f"pool_stats://800.0:local:get_interaction://{session_id}/{seq_id}")


def get_context_graphs():
    """Query all context graph session IDs via the proxy ChiMod (pool 800.0)."""
    return _monitor("local", "pool_stats://800.0:local:list_graphs")


def get_context_graph(session_id, since=0):
    """Query context graph diff nodes for a session via the proxy ChiMod (pool 800.0)."""
    q = f"query_graph://{session_id}"
    if since:
        q += f"?since={since}"
    return _monitor("local", f"pool_stats://800.0:local:{q}")


def get_context_node(session_id, seq_id):
    """Query a single context graph diff node via the proxy ChiMod (pool 800.0)."""
    return _monitor("local", f"pool_stats://800.0:local:get_node://{session_id}/{seq_id}")


def store_recovery_event(event_dict: dict) -> str:
    """Store a recovery event in CTE under Recovery_<target_session_id>.

    Returns the blob name (event_id UUID) used for storage.
    """
    import json as _json
    payload = _json.dumps(event_dict)
    result = _monitor("local", f"pool_stats://800.0:local:store_recovery_event://{payload}")
    for _, blob_name in result.items():
        if isinstance(blob_name, str):
            return blob_name
    return event_dict.get("event_id", "")


def get_recovery_events(session_id: str) -> list:
    """Return all recovery events for a session, sorted by timestamp.

    Each element is a dict with all event fields plus a ``blob_name`` key.
    """
    import json as _json
    result = _monitor("local", f"pool_stats://800.0:local:query_recovery_events://{session_id}")
    events = []
    for _, pairs in result.items():
        if not isinstance(pairs, list):
            continue
        for pair in pairs:
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            blob_name, json_str = pair[0], pair[1]
            try:
                ev = _json.loads(json_str) if isinstance(json_str, str) else json_str
                ev["blob_name"] = blob_name
                events.append(ev)
            except Exception:
                pass
    events.sort(key=lambda e: e.get("timestamp", ""))
    return events


def ack_recovery_event(session_id: str, blob_name: str) -> None:
    """Acknowledge a single recovery event (sets acknowledged=true in CTE)."""
    _monitor("local", f"pool_stats://800.0:local:ack_recovery_event://{session_id}/{blob_name}")


def get_latest_sequence_id(session_id: str) -> int:
    """Return the highest sequence_id stored for a session, or 0 if none."""
    import json as _json
    result = get_session_interactions(session_id)
    max_seq = 0
    for _, data in result.items():
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, str):
                try:
                    item = _json.loads(item)
                except Exception:
                    continue
            if isinstance(item, dict):
                seq = item.get("sequence_id", 0)
                if seq > max_seq:
                    max_seq = seq
    return max_seq


# ── Overhead stats and logging toggle ────────────────────────────────────────

def get_proxy_dispatch_stats():
    """Query dispatch + overhead stats from the proxy ChiMod (pool 800.0)."""
    return _monitor("local", "pool_stats://800.0:local:dispatch_stats")


def get_tracker_overhead_stats():
    """Query overhead stats from the tracker ChiMod (pool 810.0)."""
    return _monitor("local", "pool_stats://810.0:local:overhead_stats")


def get_untangler_overhead_stats():
    """Query overhead stats from the ctx_untangler ChiMod (pool 820.0)."""
    return _monitor("local", "pool_stats://820.0:local:overhead_stats")


def get_overhead_logging_status():
    """Return {proxy, tracker, untangler} overhead_logging enabled flags."""
    results = {}
    for name, pool in [("proxy", "800.0"), ("tracker", "810.0"),
                        ("untangler", "820.0")]:
        try:
            raw = _monitor("local",
                           f"pool_stats://{pool}:local:overhead_logging:status")
            for _, v in raw.items():
                if isinstance(v, dict):
                    results[name] = v.get("enabled", True)
                    break
            else:
                results[name] = True
        except Exception:
            results[name] = None
    return results


def set_overhead_logging(enabled: bool, component: str = "all"):
    """Toggle overhead logging on proxy/tracker/untangler.

    component: "all" | "proxy" | "tracker" | "untangler"
    """
    cmd = "overhead_logging:on" if enabled else "overhead_logging:off"
    targets = {
        "proxy": "800.0",
        "tracker": "810.0",
        "untangler": "820.0",
    }
    if component != "all":
        targets = {k: v for k, v in targets.items() if k == component}
    for pool in targets.values():
        try:
            _monitor("local", f"pool_stats://{pool}:local:{cmd}")
        except Exception:
            pass


# ── End overhead helpers ──────────────────────────────────────────────────────


def finalize():
    """Clean shutdown of the Chimaera client."""
    global _init_done
    if _init_done and _chi is not None:
        _chi.chimaera_finalize()
        _init_done = False
