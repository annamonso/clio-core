import { useCallback, useEffect, useRef, useState } from "react";
import { listInteractions, openInteractionStream } from "../api";
import type { InteractionSummary } from "../types";

const POLL_INTERVAL_MS = 5000;

export interface LiveInteractionsState {
  rows: InteractionSummary[];
  error: string | null;
  loading: boolean;
  isLive: boolean;
  refresh: () => Promise<void>;
}

export function useLiveInteractions(limit = 100): LiveInteractionsState {
  const [rows, setRows] = useState<InteractionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [isLive, setIsLive] = useState(false);

  // Refs so we can mutate without retriggering the mount effect.
  const sourceRef = useRef<EventSource | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listInteractions({ limit });
      setRows(data);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    let cancelled = false;

    const stopPoll = () => {
      if (pollRef.current != null) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };

    const startPoll = () => {
      if (pollRef.current != null) return;
      pollRef.current = setInterval(refresh, POLL_INTERVAL_MS);
    };

    const openStream = () => {
      if (sourceRef.current != null) return;
      sourceRef.current = openInteractionStream(
        (row) => {
          if (cancelled) return;
          setIsLive(true);
          setError(null);
          setRows((prev) => {
            // New rows prepend; dedupe on id in case a polling cycle raced us.
            const filtered = prev.filter((r) => r.id !== row.id);
            return [row, ...filtered].slice(0, limit);
          });
        },
        () => {
          if (cancelled) return;
          setIsLive(false);
          sourceRef.current?.close();
          sourceRef.current = null;
          // Fall back to polling; try to reopen the stream on the next tick.
          startPoll();
          setTimeout(() => {
            if (!cancelled) openStream();
          }, POLL_INTERVAL_MS);
        },
      );
    };

    void refresh().then(() => {
      if (cancelled) return;
      openStream();
    });

    return () => {
      cancelled = true;
      sourceRef.current?.close();
      sourceRef.current = null;
      stopPoll();
    };
  }, [limit, refresh]);

  return { rows, error, loading, isLive, refresh };
}
