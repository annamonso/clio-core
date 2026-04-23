import type { Interaction } from "../../types";
import { computeContextBudget } from "../../lib/contextBudget";
import { formatTokens } from "../../lib/format";

interface Props {
  interaction: Interaction;
}

function fmtPct(n: number): string {
  if (n >= 10) return `${n.toFixed(0)}%`;
  return `${n.toFixed(1)}%`;
}

export default function ContextBudgetCard({ interaction }: Props) {
  const b = computeContextBudget(interaction);

  // Nothing to show if we have no system-prompt and no reminder text.
  if (b.systemPromptChars === 0 && b.reminderChars === 0) return null;

  const total = b.inputChars || 1; // avoid /0
  const systemPct = (b.systemPromptChars / total) * 100;
  const reminderPct = (b.reminderChars / total) * 100;
  const userPct = (b.userPromptChars / total) * 100;

  // Segment colors — borrow from the existing --role-* palette so this card
  // reads visually consistent with the rest of the workspace.
  const SEG_SYSTEM = "rgb(var(--role-tool))";        // orange  = system prompt
  const SEG_REMINDER = "rgb(var(--role-unknown))";   // grey    = reminders
  const SEG_USER = "rgb(var(--role-orchestrator))";  // accent  = your prompt

  const haveTokens = b.inputTokens != null && b.inputTokens > 0;

  return (
    <div className="rounded-lg border border-border-soft bg-surface overflow-hidden">
      {/* Headline — "X% of input is CLI scaffolding" */}
      <div className="px-3 pt-3 pb-2 flex items-baseline gap-3">
        <div className="text-[10px] uppercase tracking-wider text-fg-muted">
          Context budget
        </div>
        <div className="ml-auto text-[11px] text-fg-muted tabular-nums">
          {haveTokens && b.inputTokens != null && (
            <>{formatTokens(b.inputTokens)} input tok</>
          )}
        </div>
      </div>

      <div className="px-3 pb-1">
        <div className="text-sm text-fg-primary">
          <span
            className="font-semibold tabular-nums"
            style={{ color: SEG_REMINDER }}
            title="System prompt + <system-reminder> blocks"
          >
            {fmtPct(b.scaffoldingPct)}
          </span>{" "}
          of this request is <span className="text-fg-secondary">CLI scaffolding</span>.
          <br />
          Only{" "}
          <span
            className="font-semibold tabular-nums"
            style={{ color: SEG_USER }}
          >
            {fmtPct(100 - b.scaffoldingPct)}
          </span>{" "}
          is your actual prompt.
        </div>
      </div>

      {/* Stacked bar */}
      <div className="px-3 pt-2 pb-1">
        <div
          className="flex h-3 w-full rounded overflow-hidden border border-border"
          title={`${b.systemPromptChars.toLocaleString()} sys + ${b.reminderChars.toLocaleString()} reminder + ${b.userPromptChars.toLocaleString()} user chars`}
        >
          {systemPct > 0 && (
            <div
              style={{ width: `${systemPct}%`, backgroundColor: SEG_SYSTEM }}
            />
          )}
          {reminderPct > 0 && (
            <div
              style={{ width: `${reminderPct}%`, backgroundColor: SEG_REMINDER }}
            />
          )}
          {userPct > 0 && (
            <div
              style={{ width: `${userPct}%`, backgroundColor: SEG_USER }}
            />
          )}
        </div>
      </div>

      {/* Legend / per-segment totals */}
      <div className="px-3 pt-2 pb-3 grid grid-cols-3 gap-2 text-[11px]">
        <Segment
          color={SEG_SYSTEM}
          label="System prompt"
          sub="CLI rulebook"
          chars={b.systemPromptChars}
          tokens={haveTokens ? b.systemPromptTokens : null}
        />
        <Segment
          color={SEG_REMINDER}
          label="Reminders"
          sub="MCP + skills + runtime"
          chars={b.reminderChars}
          tokens={haveTokens ? b.reminderTokens : null}
        />
        <Segment
          color={SEG_USER}
          label="Your prompt"
          sub="what you typed"
          chars={b.userPromptChars}
          tokens={haveTokens ? b.userPromptTokens : null}
          emphasise
        />
      </div>
    </div>
  );
}

function Segment({
  color,
  label,
  sub,
  chars,
  tokens,
  emphasise,
}: {
  color: string;
  label: string;
  sub: string;
  chars: number;
  tokens: number | null;
  emphasise?: boolean;
}) {
  return (
    <div
      className={
        "rounded p-2 border " +
        (emphasise
          ? "border-border bg-elevate"
          : "border-border-soft bg-canvas")
      }
    >
      <div className="flex items-center gap-1.5">
        <span
          className="w-2 h-2 rounded-sm"
          style={{ backgroundColor: color }}
        />
        <span
          className="text-[10px] uppercase tracking-wider font-semibold"
          style={{ color }}
        >
          {label}
        </span>
      </div>
      <div className="text-[10px] text-fg-muted mt-0.5">{sub}</div>
      <div className="text-xs text-fg-primary tabular-nums mt-1">
        {tokens != null ? (
          <>
            <span className="font-semibold">{tokens.toLocaleString()}</span>{" "}
            <span className="text-fg-muted">tok</span>
          </>
        ) : (
          <>
            <span className="font-semibold">{chars.toLocaleString()}</span>{" "}
            <span className="text-fg-muted">chars</span>
          </>
        )}
      </div>
      {tokens != null && (
        <div className="text-[10px] text-fg-muted tabular-nums">
          {chars.toLocaleString()} chars
        </div>
      )}
    </div>
  );
}
