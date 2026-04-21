import { useMemo, useEffect } from "react";
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
import type { ConversationData } from "../../hooks/useConversationData";
import type { PlayheadApi } from "../../hooks/usePlayhead";

interface Props {
  data: ConversationData;
  playhead: PlayheadApi;
}

const NODE_W = 200;
const NODE_H = 76;

const nodeTypes = { agent: AgentNodeComp };

function layoutDagre(nodes: Node[], edges: Edge[]) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 70, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 } };
  });
}

function roleVar(role: string): string {
  switch (role) {
    case "orchestrator": return "--role-orchestrator";
    case "subagent":     return "--role-subagent";
    case "tool":         return "--role-tool";
    default:             return "--role-unknown";
  }
}

export default function AgentFlowGraph({ data, playhead }: Props) {
  // Build raw nodes/edges from conversation data.
  const { rawNodes, rawEdges } = useMemo(() => {
    const currentTurn = data.turns[playhead.idx] ?? null;
    const pastSessions = new Set<string>();
    for (let i = 0; i <= playhead.idx && i < data.turns.length; i++) {
      pastSessions.add(data.turns[i].sessionId);
    }

    const nodes: Node<AgentNodeData>[] = (data.graph?.nodes ?? []).map((n) => ({
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
        active: currentTurn?.sessionId === n.session_id,
        past: pastSessions.has(n.session_id),
      },
    }));

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

    const edges: Edge[] = [];
    for (const [key, e] of edgeMap) {
      const traversed = currentTurn ? e.firstTurn <= currentTurn.turnNumber : false;
      const active = currentTurn ? e.firstTurn <= currentTurn.turnNumber && e.latestTurn >= currentTurn.turnNumber : false;
      const targetRoleVar = roleVar(data.roleBySession.get(e.target) ?? "unknown");
      const color = `rgb(var(${targetRoleVar})${traversed ? "" : " / 0.35"})`;
      edges.push({
        id: key,
        source: e.source,
        target: e.target,
        animated: active,
        style: {
          stroke: color,
          strokeWidth: active ? 2.5 : traversed ? 1.75 : 1.25,
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

    return { rawNodes: nodes, rawEdges: edges };
  }, [data, playhead.idx]);

  const layoutedNodes = useMemo(() => layoutDagre(rawNodes, rawEdges), [rawNodes, rawEdges]);
  const [nodes, setNodes, onNodesChange] = useNodesState(layoutedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(rawEdges);

  // Sync computed nodes/edges back into RF state when data or playhead changes.
  useEffect(() => { setNodes(layoutedNodes); }, [layoutedNodes, setNodes]);
  useEffect(() => { setEdges(rawEdges); }, [rawEdges, setEdges]);

  const handleNodeClick = (_: unknown, node: Node) => {
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
