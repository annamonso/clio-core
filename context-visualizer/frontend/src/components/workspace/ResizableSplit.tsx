import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  direction: "horizontal" | "vertical";
  /** First pane size as a fraction 0..1. */
  initial?: number;
  /** Fraction bounds for the first pane. */
  min?: number;
  max?: number;
  first: React.ReactNode;
  second: React.ReactNode;
  storageKey?: string;
  className?: string;
}

export default function ResizableSplit({
  direction,
  initial = 0.6,
  min = 0.15,
  max = 0.85,
  first,
  second,
  storageKey,
  className = "",
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [fraction, setFraction] = useState<number>(() => {
    if (storageKey) {
      const raw = localStorage.getItem(storageKey);
      const n = raw ? Number(raw) : NaN;
      if (Number.isFinite(n) && n >= min && n <= max) return n;
    }
    return initial;
  });
  const dragging = useRef(false);

  useEffect(() => {
    if (storageKey) localStorage.setItem(storageKey, String(fraction));
  }, [fraction, storageKey]);

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    dragging.current = true;
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const total = direction === "horizontal" ? rect.width : rect.height;
    const offset = direction === "horizontal" ? e.clientX - rect.left : e.clientY - rect.top;
    const f = Math.max(min, Math.min(max, offset / total));
    setFraction(f);
  }, [direction, min, max]);

  const onPointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    try { (e.target as HTMLElement).releasePointerCapture(e.pointerId); } catch { /* noop */ }
  }, []);

  const isH = direction === "horizontal";
  const flexDir = isH ? "flex-row" : "flex-col";
  const handleCls = isH
    ? "w-1 cursor-col-resize hover:bg-accent/60 bg-border-soft"
    : "h-1 cursor-row-resize hover:bg-accent/60 bg-border-soft";
  const firstStyle = isH
    ? { width: `${fraction * 100}%`, minWidth: 0 }
    : { height: `${fraction * 100}%`, minHeight: 0 };

  return (
    <div
      ref={containerRef}
      className={`flex ${flexDir} w-full h-full overflow-hidden ${className}`}
    >
      <div className="overflow-hidden" style={firstStyle}>{first}</div>
      <div
        role="separator"
        aria-orientation={isH ? "vertical" : "horizontal"}
        className={`${handleCls} transition-colors shrink-0 select-none`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      />
      <div className="flex-1 min-h-0 min-w-0 overflow-hidden">{second}</div>
    </div>
  );
}
