import { useMemo, useEffect, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Edge,
  type Node,
  useNodesState,
  useEdgesState,
  MarkerType,
} from "reactflow";
import dagre from "dagre";
import "reactflow/dist/style.css";

import AgentNodeComp, { type AgentNodeData } from "./nodes/AgentNode";
import ToolNodeComp, { type ToolNodeData } from "./nodes/ToolNode";
import type { ConversationData } from "../../hooks/useConversationData";
import type { PlayheadApi } from "../../hooks/usePlayhead";
import type { ViewMode } from "./ViewToolbar";

interface Props {
  data: ConversationData;
  playhead: PlayheadApi;
  viewMode?: ViewMode;
}

const NODE_W = 200;
const NODE_H = 76;
const NODE_H_AGG = 120;
// Transient ToolNode (sequential mode only) — ported verbatim from the
// reference project's AgentFlowGraph so the round-trip animation reads the
// same: out-arrow fires immediately, return-arrow ~300ms later.
const TOOL_W = 140;
const TOOL_H = 52;
const RETURN_EDGE_DELAY_MS = 300;

const nodeTypes = { agent: AgentNodeComp, tool: ToolNodeComp };

function layoutDagre(nodes: Node[], edges: Edge[], agentH: number) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 70, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => {
    const isTool = n.type === "tool";
    g.setNode(n.id, {
      width: isTool ? TOOL_W : NODE_W,
      height: isTool ? TOOL_H : agentH,
    });
  });
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    const isTool = n.type === "tool";
    const w = isTool ? TOOL_W : NODE_W;
    const h = isTool ? TOOL_H : agentH;
    return { ...n, position: { x: pos.x - w / 2, y: pos.y - h / 2 } };
  });
}

function uniqueToolNames(toolCalls: Record<string, unknown>[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const tc of toolCalls) {
    const name =
      typeof (tc as { name?: unknown }).name === "string" &&
      (tc as { name: string }).name
        ? (tc as { name: string }).name
        : "tool";
    if (!seen.has(name)) {
      seen.add(name);
      out.push(name);
    }
  }
  return out;
}

function roleVar(role: string): string {
  switch (role) {
    case "orchestrator": return "--role-orchestrator";
    case "subagent":     return "--role-subagent";
    case "tool":         return "--role-tool";
    default:             return "--role-unknown";
  }
}

export default function AgentFlowGraph({ data, playhead, viewMode = "sequential" }: Props) {
  const aggregate = viewMode === "aggregate";
  const currentTurnForToolNode = data.turns[playhead.idx] ?? null;
  const currentTurnIdForToolNode = currentTurnForToolNode?.id ?? null;

  // Staged edges for the sequential-mode ToolNode round-trip: show the
  // agent→tool arrow immediately, then the tool→agent return after a short
  // delay. In aggregate mode this state is inert.
  const [returnPhase, setReturnPhase] = useState<"out" | "both">("out");
  useEffect(() => {
    if (aggregate) return;
    setReturnPhase("out");
    if (!currentTurnIdForToolNode) return;
    const id = window.setTimeout(() => setReturnPhase("both"), RETURN_EDGE_DELAY_MS);
    return () => window.clearTimeout(id);
  }, [currentTurnIdForToolNode, aggregate]);

  // Build raw nodes/edges from conversation data.
  const { rawNodes, rawEdges } = useMemo(() => {
    const currentTurn = data.turns[playhead.idx] ?? null;
    const pastSessions = new Set<string>();
    for (let i = 0; i <= playhead.idx && i < data.turns.length; i++) {
      pastSessions.add(data.turns[i].sessionId);
    }

    // Tool-call frequency per session (only used in aggregate mode).
    const toolsBySession = new Map<string, Map<string, number>>();
    if (aggregate) {
      for (const t of data.turns) {
        if (!t.toolCalls || t.toolCalls.length === 0) continue;
        let bucket = toolsBySession.get(t.sessionId);
        if (!bucket) {
          bucket = new Map();
          toolsBySession.set(t.sessionId, bucket);
        }
        for (const tc of t.toolCalls) {
          const name = typeof (tc as { name?: unknown }).name === "string"
            ? (tc as { name: string }).name
            : "?";
          bucket.set(name, (bucket.get(name) ?? 0) + 1);
        }
      }
    }

    const nodes: Node<AgentNodeData | ToolNodeData>[] = (data.graph?.nodes ?? []).map((n) => {
      let toolBreakdown: { name: string; count: number }[] | undefined;
      if (aggregate) {
        const bucket = toolsBySession.get(n.session_id);
        if (bucket) {
          toolBreakdown = Array.from(bucket, ([name, count]) => ({ name, count }))
            .sort((a, b) => b.count - a.count);
        }
      }
      return {
        id: n.session_id,
        type: "agent",
        position: { x: 0, y: 0 },
        data: {
          sessionId: n.session_id,
          role: n.agent_role ?? "unknown",
          label: n.session_id.slice(0, 10) + (n.session_id.length > 10 ? "…" : ""),
          callCount: n.interaction_count,
          tokens: n.total_tokens,
          costUsd: n.total_cost_usd,
          // In aggregate mode the graph is a workflow summary, not a time-cursor view —
          // render all nodes at full opacity and skip the active/past highlighting.
          active: !aggregate && currentTurn?.sessionId === n.session_id,
          past: aggregate ? true : pastSessions.has(n.session_id),
          aggregate,
          toolBreakdown,
          host: n.host,
        },
      };
    });

    // Aggregate directed handoff edges (from_session → to_session).
    const edgeMap = new Map<string, { source: string; target: string; count: number; firstTurn: number; latestTurn: number }>();
    for (const e of data.graph?.edges ?? []) {
      const key = `${e.from_session_id}__${e.to_session_id}`;
      const existing = edgeMap.get(key);
      if (existing) {
        existing.count += 1;
        existing.latestTurn = Math.max(existing.latestTurn, e.turn_number);
      } else {
        edgeMap.set(key, {
          source: e.from_session_id,
          target: e.to_session_id,
          count: 1,
          firstTurn: e.turn_number,
          latestTurn: e.turn_number,
        });
      }
    }

    // Max edge count drives stroke-width scaling in aggregate mode.
    let maxEdgeCount = 0;
    for (const e of edgeMap.values()) {
      if (e.count > maxEdgeCount) maxEdgeCount = e.count;
    }

    const edges: Edge[] = [];
    for (const [key, e] of edgeMap) {
      const traversed = aggregate || (currentTurn ? e.firstTurn <= currentTurn.turnNumber : false);
      const active = !aggregate && currentTurn
        ? e.firstTurn <= currentTurn.turnNumber && e.latestTurn >= currentTurn.turnNumber
        : false;
      const targetRoleVar = roleVar(data.roleBySession.get(e.target) ?? "unknown");
      const color = `rgb(var(${targetRoleVar})${traversed ? "" : " / 0.35"})`;
      // In aggregate mode scale 1.25 → 6 linearly by count; otherwise the old
      // per-state widths tied to the playhead.
      const aggWidth = maxEdgeCount > 0
        ? 1.25 + (e.count / maxEdgeCount) * 4.75
        : 1.25;
      edges.push({
        id: key,
        source: e.source,
        target: e.target,
        animated: active,
        style: {
          stroke: color,
          strokeWidth: aggregate ? aggWidth : active ? 2.5 : traversed ? 1.75 : 1.25,
        },
        label: e.count > 1 ? `×${e.count}` : undefined,
        labelStyle: {
          fill: "rgb(var(--fg-secondary))",
          fontSize: 10,
        },
        labelBgStyle: {
          fill: "rgb(var(--bg-surface))",
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color,
          width: 16,
          height: 16,
        },
      });
    }

    // Sequential-mode only: render transient ToolNodes for the current turn's
    // tool_calls, with staged out-and-back arrows so the round-trip reads as a
    // sequence (out fires immediately, back arrives ~300 ms later).
    if (!aggregate && currentTurn && currentTurn.toolCalls.length > 0) {
      const stroke = "rgb(var(--role-tool))";
      const names = uniqueToolNames(currentTurn.toolCalls);
      for (const name of names) {
        const toolId = `tool::${currentTurn.sessionId}::${currentTurn.id}::${name}`;
        nodes.push({
          id: toolId,
          type: "tool",
          position: { x: 0, y: 0 },
          data: { name, turnId: currentTurn.id } as ToolNodeData,
        });
        edges.push({
          id: `${toolId}::out`,
          source: currentTurn.sessionId,
          target: toolId,
          animated: false,
          style: { stroke, strokeWidth: 2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 14, height: 14 },
        });
        if (returnPhase === "both") {
          edges.push({
            id: `${toolId}::back`,
            source: toolId,
            target: currentTurn.sessionId,
            animated: true,
            style: { stroke, strokeWidth: 1.75 },
            markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 14, height: 14 },
          });
        }
      }
    }

    return { rawNodes: nodes, rawEdges: edges };
  }, [data, playhead.idx, aggregate, returnPhase]);

  const layoutedNodes = useMemo(
    () => layoutDagre(rawNodes, rawEdges, aggregate ? NODE_H_AGG : NODE_H),
    [rawNodes, rawEdges, aggregate],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState(layoutedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(rawEdges);

  // Sync computed nodes/edges back into RF state when data or playhead changes.
  useEffect(() => { setNodes(layoutedNodes); }, [layoutedNodes, setNodes]);
  useEffect(() => { setEdges(rawEdges); }, [rawEdges, setEdges]);

  const handleNodeClick = (_: unknown, node: Node) => {
    // Transient ToolNodes don't map to a session — ignore clicks on them.
    if (node.type === "tool") return;
    // Jump playhead to the first turn in this session at or after current idx.
    const idx = data.turns.findIndex((t) => t.sessionId === node.id);
    if (idx >= 0) playhead.setIdx(idx);
  };

  if ((data.graph?.nodes ?? []).length === 0) {
    return (
      <div className="h-full w-full flex items-center justify-center text-fg-muted text-sm">
        No agents detected in this conversation.
      </div>
    );
  }

  return (
    <div className="h-full w-full bg-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="rgb(var(--border-soft))" gap={16} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(n) => {
            const role = (n.data as AgentNodeData | undefined)?.role ?? "unknown";
            return `rgb(var(${roleVar(role)}))`;
          }}
          maskColor="rgb(var(--bg-canvas) / 0.7)"
          pannable
          zoomable
        />
      </ReactFlow>
    </div>
  );
}
