import { useEffect } from "react";

export interface ToastState {
  message: string;
  type: "success" | "error";
}

interface Props {
  toast: ToastState | null;
  onDismiss: () => void;
  /**
   * Milliseconds to auto-dismiss. Pass `null` to disable auto-dismiss when
   * the parent component controls visibility (e.g. tied to playhead state).
   * Defaults to 4000.
   */
  autoDismissMs?: number | null;
  /** Hide the leading ✓/✕ glyph. Default false. */
  hideIcon?: boolean;
  /** Hide the trailing ✕ close button. Default false. */
  hideClose?: boolean;
}

export default function Toast({
  toast,
  onDismiss,
  autoDismissMs = 4000,
  hideIcon = false,
  hideClose = false,
}: Props) {
  useEffect(() => {
    if (!toast || autoDismissMs == null) return;
    const id = setTimeout(onDismiss, autoDismissMs);
    return () => clearTimeout(id);
  }, [toast, onDismiss, autoDismissMs]);

  if (!toast) return null;

  return (
    <div
      className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-lg shadow-xl border text-sm ${
        toast.type === "success"
          ? "bg-emerald-900 border-emerald-700 text-emerald-200"
          : "bg-red-900 border-red-700 text-red-200"
      }`}
    >
      {!hideIcon && <span>{toast.type === "success" ? "✓" : "✕"}</span>}
      <span>{toast.message}</span>
      {!hideClose && (
        <button onClick={onDismiss} className="ml-2 opacity-60 hover:opacity-100">
          ✕
        </button>
      )}
    </div>
  );
}
