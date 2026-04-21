import { useMemo, useRef, useState, useEffect, useCallback } from "react";
import { scaleLinear } from "@visx/scale";
import { AxisBottom } from "@visx/axis";
import { Group } from "@visx/group";
import type { ConversationData, NormalizedTurn } from "../../hooks/useConversationData";
import type { PlayheadApi } from "../../hooks/usePlayhead";
import { PLAYHEAD_SPEEDS } from "../../hooks/usePlayhead";

interface Props {
  data: ConversationData;
  playhead: PlayheadApi;
}

const LANE_HEIGHT = 28;
const LANE_LABEL_WIDTH = 140;
const TOP_PADDING = 28;       // leaves room for the axis
const BOTTOM_PADDING = 32;
const MIN_BAR_WIDTH = 3;

function roleColorVar(role: string): string {
  switch (role) {
    case "orchestrator": return "var(--role-orchestrator)";
    case "subagent":     return "var(--role-subagent)";
    case "tool":         return "var(--role-tool)";
    default:             return "var(--role-unknown)";
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function TimelineView({ data, playhead }: Props) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(600);
  const [hoverTurn, setHoverTurn] = useState<NormalizedTurn | null>(null);

  useEffect(() => {
    if (!wrapperRef.current) return;
    const el = wrapperRef.current;
    const obs = new ResizeObserver((entries) => {
      for (const e of entries) setWidth(e.contentRect.width);
    });
    obs.observe(el);
    setWidth(el.clientWidth);
    return () => obs.disconnect();
  }, []);

  const { turns, lanes, roleBySession } = data;

  const { t0, duration } = useMemo(() => {
    if (turns.length === 0) return { t0: 0, duration: 1 };
    const start = turns[0].startTs;
    const last = turns[turns.length - 1];
    const end = last.startTs + (last.hasLatency ? last.latencyMs : 0);
    return { t0: start, duration: Math.max(end - start, 1) };
  }, [turns]);

  const chartWidth = Math.max(width - LANE_LABEL_WIDTH - 16, 200);
  const chartHeight = lanes.length * LANE_HEIGHT;
  const svgHeight = TOP_PADDING + chartHeight + BOTTOM_PADDING;

  const xScale = useMemo(
    () => scaleLinear({
      domain: [0, duration],
      range: [0, chartWidth],
    }),
    [duration, chartWidth],
  );

  const laneY = useCallback((sessionId: string) => {
    const i = lanes.indexOf(sessionId);
    return TOP_PADDING + (i < 0 ? 0 : i) * LANE_HEIGHT + (LANE_HEIGHT - 18) / 2;
  }, [lanes]);

  const currentTurn = turns[playhead.idx] ?? null;
  const playheadX = currentTurn ? xScale(currentTurn.startTs - t0) : 0;

  const onScrubberDrag = useCallback((clientX: number, rect: DOMRect) => {
    if (turns.length === 0) return;
    const x = Math.max(0, Math.min(chartWidth, clientX - rect.left));
    const t = xScale.invert(x);
    // Find closest turn by startTs.
    let nearestIdx = 0;
    let nearestDist = Infinity;
    for (let i = 0; i < turns.length; i++) {
      const d = Math.abs((turns[i].startTs - t0) - t);
      if (d < nearestDist) { nearestDist = d; nearestIdx = i; }
    }
    playhead.setIdx(nearestIdx);
  }, [turns, xScale, t0, chartWidth, playhead]);

  const scrubberDragging = useRef(false);

  return (
    <div ref={wrapperRef} className="h-full w-full bg-canvas border-t border-border-soft flex flex-col">
      {/* Controls */}
      <div className="px-3 py-1.5 border-b border-border-soft flex items-center gap-3 shrink-0">
        <button
          onClick={playhead.toggle}
          className="w-7 h-7 rounded-md bg-elevate hover:bg-hover text-fg-primary flex items-center justify-center"
          title={playhead.isPlaying ? "Pause (space)" : "Play (space)"}
        >
          {playhead.isPlaying ? (
            <svg width="12" height="12" viewBox="0 0 12 12"><rect x="3" y="2" width="2" height="8" fill="currentColor"/><rect x="7" y="2" width="2" height="8" fill="currentColor"/></svg>
          ) : (
            <svg width="12" height="12" viewBox="0 0 12 12"><polygon points="3,2 10,6 3,10" fill="currentColor"/></svg>
          )}
        </button>
        <button
          onClick={() => playhead.step(-1)}
          className="w-7 h-7 rounded-md bg-elevate hover:bg-hover text-fg-secondary flex items-center justify-center"
          title="Previous turn (←)"
        ><svg width="10" height="10" viewBox="0 0 10 10"><polygon points="7,1 3,5 7,9" fill="currentColor"/></svg></button>
        <button
          onClick={() => playhead.step(1)}
          className="w-7 h-7 rounded-md bg-elevate hover:bg-hover text-fg-secondary flex items-center justify-center"
          title="Next turn (→)"
        ><svg width="10" height="10" viewBox="0 0 10 10"><polygon points="3,1 7,5 3,9" fill="currentColor"/></svg></button>

        <span className="text-xs text-fg-muted tabular-nums">
          {playhead.idx + 1} / {playhead.count}
        </span>

        <div className="flex items-center gap-1 ml-2">
          {PLAYHEAD_SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => playhead.setSpeed(s)}
              className={`px-2 py-0.5 text-[10px] rounded ${
                playhead.speed === s ? "bg-accent text-canvas" : "bg-elevate text-fg-muted hover:text-fg-secondary"
              }`}
            >{s}x</button>
          ))}
        </div>

        <div className="flex-1" />

        {hoverTurn && (
          <div className="text-[11px] text-fg-muted flex gap-3">
            <span className="font-mono">turn {hoverTurn.turnNumber}</span>
            <span>{hoverTurn.agentRole}</span>
            <span className="tabular-nums">{formatDuration(hoverTurn.hasLatency ? hoverTurn.latencyMs : 0)}</span>
          </div>
        )}
      </div>

      {/* Chart */}
      <div className="flex-1 overflow-auto relative">
        <svg width={width} height={svgHeight} className="block">
          {/* Lane backgrounds + labels */}
          {lanes.map((sid, i) => {
            const y = TOP_PADDING + i * LANE_HEIGHT;
            const role = roleBySession.get(sid) ?? "unknown";
            const isCurrent = currentTurn?.sessionId === sid;
            return (
              <Group key={sid}>
                <rect
                  x={0}
                  y={y}
                  width={width}
                  height={LANE_HEIGHT}
                  fill={isCurrent ? "rgb(var(--bg-elevate) / 0.5)" : i % 2 === 0 ? "rgb(var(--bg-surface) / 0.3)" : "transparent"}
                />
                <line x1={LANE_LABEL_WIDTH} y1={y + LANE_HEIGHT} x2={width} y2={y + LANE_HEIGHT}
                  stroke="rgb(var(--border-soft))" strokeWidth="1" />
                <circle cx={10} cy={y + LANE_HEIGHT / 2} r={4} fill={`rgb(${roleColorVar(role)})`} />
                <text
                  x={22} y={y + LANE_HEIGHT / 2 + 4}
                  fontSize="11"
                  fill="rgb(var(--fg-secondary))"
                  style={{ fontFamily: "ui-monospace, monospace" }}
                >
                  {sid.length > 14 ? sid.slice(0, 14) + "…" : sid}
                </text>
                <text
                  x={LANE_LABEL_WIDTH - 6} y={y + LANE_HEIGHT / 2 + 4}
                  fontSize="10"
                  textAnchor="end"
                  fill="rgb(var(--fg-muted))"
                >
                  {role}
                </text>
              </Group>
            );
          })}

          {/* Bars */}
          <Group left={LANE_LABEL_WIDTH}>
            {turns.map((turn, i) => {
              const x = xScale(turn.startTs - t0);
              const w = Math.max(xScale(turn.hasLatency ? turn.latencyMs : 0), MIN_BAR_WIDTH);
              const y = laneY(turn.sessionId);
              const isActive = i === playhead.idx;
              const isPast = i < playhead.idx;
              const color = `rgb(${roleColorVar(turn.agentRole)})`;
              return (
                <g key={turn.id}
                  onMouseEnter={() => setHoverTurn(turn)}
                  onMouseLeave={() => setHoverTurn(null)}
                  onClick={() => playhead.setIdx(i)}
                  style={{ cursor: "pointer" }}
                >
                  <rect
                    x={x} y={y} width={w} height={18} rx={3}
                    fill={color}
                    opacity={isActive ? 1 : isPast ? 0.65 : 0.25}
                    stroke={isActive ? "rgb(var(--fg-primary))" : "transparent"}
                    strokeWidth={isActive ? 1.5 : 0}
                  />
                </g>
              );
            })}
          </Group>

          {/* Playhead line */}
          {currentTurn && (
            <Group left={LANE_LABEL_WIDTH}>
              <line
                x1={playheadX} x2={playheadX}
                y1={TOP_PADDING - 6} y2={TOP_PADDING + chartHeight + 2}
                stroke="rgb(var(--accent))" strokeWidth="1.5"
                strokeDasharray="3 3"
              />
              <circle cx={playheadX} cy={TOP_PADDING - 6} r={4} fill="rgb(var(--accent))" />
            </Group>
          )}

          {/* Axis */}
          <Group left={LANE_LABEL_WIDTH} top={TOP_PADDING + chartHeight + 2}>
            <AxisBottom
              scale={xScale}
              numTicks={6}
              tickFormat={(v) => formatDuration(Number(v))}
              stroke="rgb(var(--border))"
              tickStroke="rgb(var(--border))"
              tickLabelProps={() => ({
                fill: "rgb(var(--fg-muted))",
                fontSize: 10,
                textAnchor: "middle",
              })}
            />
          </Group>

          {/* Scrub overlay — captures drag anywhere in chart area */}
          <rect
            x={LANE_LABEL_WIDTH} y={TOP_PADDING - 12}
            width={chartWidth} height={chartHeight + 14}
            fill="transparent"
            style={{ cursor: "ew-resize" }}
            onPointerDown={(e) => {
              scrubberDragging.current = true;
              (e.target as Element).setPointerCapture?.(e.pointerId);
              onScrubberDrag(e.clientX, (e.currentTarget as SVGRectElement).ownerSVGElement!.getBoundingClientRect());
            }}
            onPointerMove={(e) => {
              if (!scrubberDragging.current) return;
              onScrubberDrag(e.clientX, (e.currentTarget as SVGRectElement).ownerSVGElement!.getBoundingClientRect());
            }}
            onPointerUp={(e) => {
              scrubberDragging.current = false;
              try { (e.target as Element).releasePointerCapture?.(e.pointerId); } catch { /* noop */ }
            }}
          />
        </svg>
      </div>
    </div>
  );
}
