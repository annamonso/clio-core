import { useEffect } from "react";

export interface ToastState {
  message: string;
  type: "success" | "error";
}

interface Props {
  toast: ToastState | null;
  onDismiss: () => void;
}

export default function Toast({ toast, onDismiss }: Props) {
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(onDismiss, 4000);
    return () => clearTimeout(id);
  }, [toast, onDismiss]);

  if (!toast) return null;

  return (
    <div
      className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-lg shadow-xl border text-sm ${
        toast.type === "success"
          ? "bg-emerald-900 border-emerald-700 text-emerald-200"
          : "bg-red-900 border-red-700 text-red-200"
      }`}
    >
      <span>{toast.type === "success" ? "✓" : "✕"}</span>
      <span>{toast.message}</span>
      <button onClick={onDismiss} className="ml-2 opacity-60 hover:opacity-100">
        ✕
      </button>
    </div>
  );
}
