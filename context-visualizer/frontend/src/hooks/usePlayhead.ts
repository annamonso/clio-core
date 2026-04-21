import { useCallback, useEffect, useRef, useState } from "react";

export interface PlayheadApi {
  idx: number;
  count: number;
  isPlaying: boolean;
  speed: number;
  setIdx: (idx: number) => void;
  step: (delta: number) => void;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  setSpeed: (s: number) => void;
  reset: () => void;
}

const SPEEDS = [0.5, 1, 2, 4];
const BASE_TICK_MS = 700;

/**
 * Tracks an advancing cursor across a fixed-length sequence (typically
 * turns in a conversation). Play/pause advances the cursor on a tick.
 */
export function usePlayhead(count: number): PlayheadApi {
  const [idx, setIdxState] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeedState] = useState(1);
  const timerRef = useRef<number | null>(null);

  // Clamp if count shrinks.
  useEffect(() => {
    if (idx >= count) setIdxState(Math.max(0, count - 1));
  }, [count, idx]);

  // Pause when count hits 0.
  useEffect(() => {
    if (count === 0 && isPlaying) setIsPlaying(false);
  }, [count, isPlaying]);

  useEffect(() => {
    if (!isPlaying || count === 0) {
      if (timerRef.current != null) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }
    const tickMs = BASE_TICK_MS / speed;
    timerRef.current = window.setInterval(() => {
      setIdxState((prev) => {
        const next = prev + 1;
        if (next >= count) {
          setIsPlaying(false);
          return prev;
        }
        return next;
      });
    }, tickMs);
    return () => {
      if (timerRef.current != null) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [isPlaying, speed, count]);

  const setIdx = useCallback((i: number) => {
    setIdxState(Math.max(0, Math.min(count - 1, i)));
  }, [count]);

  const step = useCallback((delta: number) => {
    setIdxState((prev) => Math.max(0, Math.min(count - 1, prev + delta)));
  }, [count]);

  const play = useCallback(() => {
    if (count === 0) return;
    setIdxState((prev) => (prev >= count - 1 ? 0 : prev));
    setIsPlaying(true);
  }, [count]);

  const pause = useCallback(() => setIsPlaying(false), []);
  const toggle = useCallback(() => {
    setIsPlaying((p) => {
      if (!p && count === 0) return false;
      if (!p) setIdxState((prev) => (prev >= count - 1 ? 0 : prev));
      return !p;
    });
  }, [count]);
  const reset = useCallback(() => {
    setIsPlaying(false);
    setIdxState(0);
  }, []);

  const setSpeed = useCallback((s: number) => {
    setSpeedState(SPEEDS.includes(s) ? s : 1);
  }, []);

  return { idx, count, isPlaying, speed, setIdx, step, play, pause, toggle, setSpeed, reset };
}

export const PLAYHEAD_SPEEDS = SPEEDS;
