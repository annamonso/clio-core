# inter_agent_relay — MCP server for cross-node agent calls

A tiny MCP (Model Context Protocol) server that an agent can call to:

1. Log the start of an inter-agent call to the context-visualizer leader.
2. Make an HTTP call to a peer agent on another node.
3. Log the completion (with latency and status).

The logged events power the `/scenarios/<sid>` view in the context-visualizer:
peer agents appear as nodes, cross-node calls as dashed edges.

## Install

Set up a venv and install. Uses only `mcp` (stdio) and `requests`.

```bash
cd context-exploration-engine/agent-interceptor/inter_agent_relay
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Agent MCP config

Point `claude` at the relay via an MCP config:

```jsonc
// ~/.config/claude-code/config.json (or project-local .mcp.json)
{
  "mcpServers": {
    "inter-agent": {
      "command": "/abs/path/inter_agent_relay/.venv/bin/inter-agent-relay",
      "env": {
        "DTP_LEADER_URL": "http://ares-comp-11:5000",
        "DTP_SCENARIO_ID": "expt-1",
        "DTP_FROM_HOST": "ares-comp-11",
        "DTP_FROM_SESSION": "planner-a"
      }
    }
  }
}
```

Env vars provide scenario defaults so tool calls don't have to repeat them.

## Tools exposed

| Tool | Purpose |
|---|---|
| `call_remote_agent` | End-to-end: log-start → HTTP POST to peer → log-done (with latency + status). Returns the peer's reply. |
| `log_remote_call_start` | Just emit a start event and return a `correlation_id` caller must pass to `log_remote_call_done`. |
| `log_remote_call_done`  | Close out a previous start event with status + latency. |

Use `call_remote_agent` for the common case. The two low-level tools exist
for cases where the remote transport is not HTTP (SSH, filesystem, SLURM
signals) and the agent still wants the event stitched on the timeline.
