import { useEffect, useMemo } from "react";
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
import HostGroupNode, { type HostGroupData } from "./nodes/HostGroupNode";
import type { ScenarioGraph } from "../../types";

interface Props {
  graph: ScenarioGraph;
  onAgentClick?: (agentId: string) => void;
  onHostClick?: (host: string) => void;
  onEdgeSelect?: (correlationId: string) => void;
}

const NODE_W = 200;
const NODE_H = 110;
const GROUP_PAD_X = 28;
const GROUP_PAD_TOP = 56;   // room for the "node · <host>" header + totals line
const GROUP_PAD_BOTTOM = 20;

const nodeTypes = { agent: AgentNodeComp, hostGroup: HostGroupNode };

/**
 * Evenly-spaced hue per host within a scenario. With N hosts we walk around
 * the color wheel in N equal steps, starting at a pleasant blue so the first
 * host isn't fire-engine red. Any two hosts in the same scenario are visibly
 * distinct regardless of how similar their hostnames look.
 */
function buildHostHueMap(hosts: Iterable<string>): Map<string, number> {
  const unique = Array.from(new Set(hosts)).sort();
  const step = 360 / Math.max(unique.length, 1);
  const offset = 200; // start blue-ish
  const map = new Map<string, number>();
  unique.forEach((h, i) => {
    map.set(h, Math.round((offset + i * step) % 360));
  });
  return map;
}

function layoutDagreFlat(nodes: Node[], edges: Edge[]) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 60, ranksep: 120, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 } };
  });
}

export default function ScenarioFlowGraph({
  graph,
  onAgentClick,
  onHostClick,
  onEdgeSelect,
}: Props) {
  // Evenly-spaced per-host hues for this scenario — shared between group
  // rectangles and the agent chips inside them so the colors tie together.
  const hueMap = useMemo(
    () => buildHostHueMap(graph.agents.map((a) => a.host || "unknown")),
    [graph.agents],
  );

  const { rawNodes, rawEdges } = useMemo(() => {
    // ─── 1. Agent child nodes (positioning comes after dagre) ─────────────
    const agentNodes: Node<AgentNodeData>[] = graph.agents.map((a) => ({
      id: a.agent_id,
      type: "agent",
      position: { x: 0, y: 0 },
      data: {
        sessionId: a.session_id,
        role: "peer",
        label:
          a.session_id.slice(0, 14) +
          (a.session_id.length > 14 ? "…" : ""),
        callCount: a.interaction_count,
        tokens: a.total_tokens,
        costUsd: a.total_cost_usd,
        active: false,
        past: true,
        aggregate: true,
        host: a.host,
        hostHueDeg: hueMap.get(a.host || "unknown"),
      },
    }));

    // ─── 2. Aggregate inter-agent edges (pair + direction) ───────────────
    const edgeMap = new Map<
      string,
      {
        source: string;
        target: string;
        count: number;
        okCount: number;
        errCount: number;
        lastTs: string;
        tools: Set<string>;
      }
    >();
    for (const e of graph.edges) {
      if (!e.from_session_id || !e.to_session_id) continue;
      const key = `${e.from_session_id}__${e.to_session_id}`;
      const slot = edgeMap.get(key) ?? {
        source: e.from_session_id,
        target: e.to_session_id,
        count: 0,
        okCount: 0,
        errCount: 0,
        lastTs: "",
        tools: new Set<string>(),
      };
      slot.count += 1;
      if ((e.status || "").startsWith("error")) slot.errCount += 1;
      else slot.okCount += 1;
      if (e.tool_name) slot.tools.add(e.tool_name);
      const ts = e.ts_done || e.ts_start || "";
      if (ts && ts > slot.lastTs) slot.lastTs = ts;
      edgeMap.set(key, slot);
    }

    const edges: Edge[] = [];
    for (const [key, e] of edgeMap) {
      const hasError = e.errCount > 0;
      const color = hasError
        ? "rgb(var(--role-error, 220 38 38))"
        : "rgb(var(--role-subagent))";
      const tooltip = Array.from(e.tools).join(", ") || "inter-agent call";
      // Grab the first (earliest) raw edge in this pair so a click can open
      // detail for something specific. A future enhancement could show all.
      const firstForPair = graph.edges.find(
        (re) => re.from_session_id === e.source && re.to_session_id === e.target,
      );
      edges.push({
        id: key,
        source: e.source,
        target: e.target,
        animated: false,
        style: {
          stroke: color,
          strokeWidth: 1.75,
          strokeDasharray: "6 4",
          cursor: "pointer",
        },
        label: e.count > 1 ? `×${e.count}` : tooltip.slice(0, 24),
        labelStyle: { fill: "rgb(var(--fg-secondary))", fontSize: 10 },
        labelBgStyle: { fill: "rgb(var(--bg-surface))" },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color,
          width: 16,
          height: 16,
        },
        data: { correlationId: firstForPair?.correlation_id ?? "" },
      });
    }

    return { rawNodes: agentNodes, rawEdges: edges };
  }, [graph, hueMap]);

  // ─── 3. Run dagre on the flat agent graph first ─────────────────────────
  const layoutedAgents = useMemo(
    () => layoutDagreFlat(rawNodes, rawEdges),
    [rawNodes, rawEdges],
  );

  // ─── 4. Bucket laid-out agents by host → build parent groups ───────────
  const nodesWithGroups = useMemo(() => {
    // Count inter-agent edges per host for the group header.
    const outgoingByHost = new Map<string, number>();
    const incomingByHost = new Map<string, number>();
    {
      const agentHost = new Map<string, string>();
      for (const a of graph.agents) {
        agentHost.set(a.agent_id, a.host || "unknown");
      }
      for (const e of graph.edges) {
        const fh = agentHost.get(e.from_session_id);
        const th = agentHost.get(e.to_session_id);
        if (fh) outgoingByHost.set(fh, (outgoingByHost.get(fh) ?? 0) + 1);
        if (th) incomingByHost.set(th, (incomingByHost.get(th) ?? 0) + 1);
      }
    }

    const byHost = new Map<string, Node<AgentNodeData>[]>();
    for (const n of layoutedAgents) {
      const host = n.data.host || "unknown";
      if (!byHost.has(host)) byHost.set(host, []);
      byHost.get(host)!.push(n);
    }

    const result: Node[] = [];

    // ReactFlow requires: parent nodes appear BEFORE their children in the
    // array. So we push the group first, then its children.
    for (const [host, members] of byHost) {
      if (!members.length) continue;

      const xs = members.map((a) => a.position.x);
      const ys = members.map((a) => a.position.y);
      const minX = Math.min(...xs) - GROUP_PAD_X;
      const minY = Math.min(...ys) - GROUP_PAD_TOP;
      const maxX = Math.max(...xs.map((x) => x + NODE_W)) + GROUP_PAD_X;
      const maxY = Math.max(...ys.map((y) => y + NODE_H)) + GROUP_PAD_BOTTOM;

      const parentId = `host__${host}`;

      // Compute per-host aggregates from the scenario graph source of truth.
      let agentCount = 0;
      let totalTokens = 0;
      let totalCostUsd = 0;
      for (const a of graph.agents) {
        if ((a.host || "unknown") !== host) continue;
        agentCount += 1;
        totalTokens += a.total_tokens;
        totalCostUsd += a.total_cost_usd;
      }

      const groupData: HostGroupData = {
        host,
        hue: hueMap.get(host) ?? 200,
        agentCount,
        totalTokens,
        totalCostUsd,
        outgoingCalls: outgoingByHost.get(host) ?? 0,
        incomingCalls: incomingByHost.get(host) ?? 0,
      };

      result.push({
        id: parentId,
        type: "hostGroup",
        position: { x: minX, y: minY },
        style: { width: maxX - minX, height: maxY - minY, zIndex: 0 },
        data: groupData,
        // Groups shouldn't be draggable — they're scaffolding — but they
        // do need to be clickable so users can open the host detail panel.
        draggable: false,
        selectable: false,
      });

      for (const a of members) {
        result.push({
          ...a,
          parentNode: parentId,
          extent: "parent",
          // Child coordinates are relative to the parent's origin.
          position: {
            x: a.position.x - minX,
            y: a.position.y - minY,
          },
          // Child nodes paint above the group.
          zIndex: 1,
        });
      }
    }

    return result;
  }, [layoutedAgents, graph, hueMap]);

  const [nodes, setNodes, onNodesChange] = useNodesState(nodesWithGroups);
  const [edges, setEdges, onEdgesChange] = useEdgesState(rawEdges);

  useEffect(() => {
    setNodes(nodesWithGroups);
  }, [nodesWithGroups, setNodes]);
  useEffect(() => {
    setEdges(rawEdges);
  }, [rawEdges, setEdges]);

  const handleClick = (_: unknown, node: Node) => {
    if (node.type === "agent") onAgentClick?.(node.id);
    else if (node.type === "hostGroup") {
      const host = (node.data as HostGroupData | undefined)?.host ?? "";
      onHostClick?.(host);
    }
  };

  const handleEdgeClick = (_: unknown, edge: Edge) => {
    const corr = (edge.data as { correlationId?: string } | undefined)?.correlationId;
    if (corr) onEdgeSelect?.(corr);
  };

  if (graph.agents.length === 0) {
    return (
      <div className="h-full w-full flex items-center justify-center text-fg-muted text-sm">
        No peer agents have exchanged messages in this scenario yet.
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
        onNodeClick={handleClick}
        onEdgeClick={handleEdgeClick}
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
          maskColor="rgb(var(--bg-canvas) / 0.7)"
          pannable
          zoomable
        />
      </ReactFlow>
    </div>
  );
}
