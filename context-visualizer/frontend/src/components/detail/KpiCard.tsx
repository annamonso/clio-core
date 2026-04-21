interface SubMetric {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "error" | "muted" | "default";
}

interface Props {
  title: string;
  headline?: string;
  headlineTone?: "ok" | "warn" | "error" | "muted" | "default";
  sub?: SubMetric[];
  children?: React.ReactNode;
  className?: string;
}

function toneColor(tone: string | undefined): string | undefined {
  switch (tone) {
    case "ok":    return "rgb(var(--ok))";
    case "warn":  return "rgb(var(--warn))";
    case "error": return "rgb(var(--error))";
    case "muted": return "rgb(var(--fg-muted))";
    default:      return undefined;
  }
}

export default function KpiCard({ title, headline, headlineTone, sub = [], children, className = "" }: Props) {
  return (
    <div className={`rounded-lg border border-border-soft bg-surface px-4 py-3 ${className}`}>
      <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
        {title}
      </div>
      {headline && (
        <div
          className="text-lg font-semibold tabular-nums"
          style={{ color: toneColor(headlineTone) ?? "rgb(var(--fg-primary))" }}
        >
          {headline}
        </div>
      )}
      {children && <div className="mt-2">{children}</div>}
      {sub.length > 0 && (
        <div className="mt-2 space-y-0.5">
          {sub.map((s) => (
            <div key={s.label} className="flex items-center justify-between text-xs">
              <span className="text-fg-muted">{s.label}</span>
              <span
                className="tabular-nums font-medium"
                style={{ color: toneColor(s.tone) ?? "rgb(var(--fg-secondary))" }}
              >
                {s.value}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
