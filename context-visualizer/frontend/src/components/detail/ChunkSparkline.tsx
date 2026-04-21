import { useMemo, useRef, useState, useEffect } from "react";
import { scaleLinear } from "@visx/scale";
import type { StreamChunk } from "../../types";
import { formatLatency } from "../../lib/format";

interface Props {
  chunks: StreamChunk[];
}

const HEIGHT = 60;
const MARGIN_X = 8;
const MARGIN_Y = 8;
const TARGET_BUCKETS = 24;

export default function ChunkSparkline({ chunks }: Props) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(320);

  useEffect(() => {
    if (!wrapperRef.current) return;
    const el = wrapperRef.current;
    const obs = new ResizeObserver((entries) => {
      for (const e of entries) setWidth(Math.max(e.contentRect.width, 120));
    });
    obs.observe(el);
    setWidth(Math.max(el.clientWidth, 120));
    return () => obs.disconnect();
  }, []);

  const { buckets, bucketWidthMs, start, end } = useMemo(() => {
    if (chunks.length < 2) {
      return { buckets: [] as number[], bucketWidthMs: 0, start: 0, end: 0 };
    }
    const ts = chunks.map((c) => new Date(c.timestamp).getTime()).filter((n) => !Number.isNaN(n));
    if (ts.length < 2) return { buckets: [] as number[], bucketWidthMs: 0, start: 0, end: 0 };
    const min = Math.min(...ts);
    const max = Math.max(...ts);
    const span = Math.max(max - min, 1);
    const bucketCount = Math.min(TARGET_BUCKETS, chunks.length);
    const bw = span / bucketCount;
    const counts = new Array(bucketCount).fill(0);
    for (const t of ts) {
      const idx = Math.min(bucketCount - 1, Math.floor((t - min) / bw));
      counts[idx] += 1;
    }
    return { buckets: counts, bucketWidthMs: bw, start: min, end: max };
  }, [chunks]);

  if (chunks.length < 2) {
    return (
      <div ref={wrapperRef} className="text-xs text-fg-muted h-[60px] flex items-center">
        {chunks.length === 0 ? "No stream chunks." : "Only 1 chunk — no arrival pattern."}
      </div>
    );
  }

  const chartHeight = HEIGHT - MARGIN_Y * 2;
  const chartWidth = Math.max(width - MARGIN_X * 2, 80);
  const maxCount = Math.max(...buckets, 1);

  const xScale = scaleLinear({ domain: [0, buckets.length], range: [0, chartWidth] });
  const yScale = scaleLinear({ domain: [0, maxCount], range: [chartHeight, 0] });

  const barWidth = chartWidth / buckets.length;

  return (
    <div ref={wrapperRef} className="w-full">
      <svg width={width} height={HEIGHT} className="block">
        <g transform={`translate(${MARGIN_X}, ${MARGIN_Y})`}>
          {/* baseline */}
          <line
            x1={0} x2={chartWidth}
            y1={chartHeight} y2={chartHeight}
            stroke="rgb(var(--border-soft))"
            strokeWidth={1}
          />

          {buckets.map((count, i) => {
            const h = chartHeight - yScale(count);
            const x = xScale(i);
            return (
              <rect
                key={i}
                x={x + 0.5}
                y={chartHeight - h}
                width={Math.max(barWidth - 1, 1)}
                height={h}
                fill="rgb(var(--accent))"
                opacity={0.7}
              >
                <title>
                  {count} chunk{count === 1 ? "" : "s"} · {formatLatency(i * bucketWidthMs)}–{formatLatency((i + 1) * bucketWidthMs)}
                </title>
              </rect>
            );
          })}
        </g>
      </svg>
      <div className="flex justify-between text-[10px] text-fg-muted mt-0.5">
        <span>{formatLatency(0)}</span>
        <span>{buckets.length} buckets × {formatLatency(bucketWidthMs)}</span>
        <span>{formatLatency(end - start)}</span>
      </div>
    </div>
  );
}
