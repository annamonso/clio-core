"""File-backed store for InterAgentMessage events.

Phase 1 uses a JSONL file per scenario under ``~/.dt_provenance/inter_agent/``.
Appends are O(1) and atomic (single writev). A later phase can move the
backing store into CTE without changing this module's public API — the
blueprint and adapter only talk to ``get_store()``.

Design notes:
  - Two-phase records ("start" written at call initiation, "done" written
    when the remote returns) are stitched on read by ``correlation_id``.
    The store itself just appends; stitching lives in the adapter.
  - Records are immutable: to "update" a start into a done, callers emit a
    second record with the same correlation_id and ``phase="done"``.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional


_ISO = "%Y-%m-%dT%H:%M:%S.%fZ"


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime(_ISO)


@dataclass
class InterAgentMessage:
    """One inter-agent call event.

    A single logical call emits two of these: one with ``phase='start'`` when
    the caller MCP tool fires, and one with ``phase='done'`` when the remote
    replies. Adapters stitch them on the shared ``correlation_id``.
    """

    event_id: str
    scenario_id: str
    correlation_id: str
    phase: str  # "start" | "done"
    from_host: str
    from_session: str
    to_host: str
    to_session: str
    ts: str  # ISO 8601 UTC
    kind: str = "mcp_call"  # mcp_call | tool_invoke | direct_message
    tool_name: str = ""
    payload_digest: str = ""
    payload_preview: str = ""
    status: str = ""  # "ok" | "error:<msg>" | "" while in-flight
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InterAgentMessage":
        # Tolerate missing fields on pre-existing records.
        return cls(
            event_id=str(d.get("event_id") or uuid.uuid4().hex),
            scenario_id=str(d.get("scenario_id") or ""),
            correlation_id=str(d.get("correlation_id") or ""),
            phase=str(d.get("phase") or "done"),
            from_host=str(d.get("from_host") or ""),
            from_session=str(d.get("from_session") or ""),
            to_host=str(d.get("to_host") or ""),
            to_session=str(d.get("to_session") or ""),
            ts=str(d.get("ts") or _iso_now()),
            kind=str(d.get("kind") or "mcp_call"),
            tool_name=str(d.get("tool_name") or ""),
            payload_digest=str(d.get("payload_digest") or ""),
            payload_preview=str(d.get("payload_preview") or ""),
            status=str(d.get("status") or ""),
            latency_ms=float(d.get("latency_ms") or 0.0),
        )


def _safe_scenario(sid: str) -> str:
    """Sanitize scenario_id into a safe filename fragment."""
    return "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in sid)[:120]


class InterAgentStore:
    """Thread-safe append-only scenario store.

    Paths:
        ``<root>/inter_agent/<scenario_id>.jsonl``
    """

    def __init__(self, root: Optional[os.PathLike] = None) -> None:
        if root is None:
            root = Path(os.environ.get("DTP_STATE_DIR", "")) if os.environ.get("DTP_STATE_DIR") else Path.home() / ".dt_provenance"
        self._root = Path(root) / "inter_agent"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path_for(self, scenario_id: str) -> Path:
        return self._root / f"{_safe_scenario(scenario_id)}.jsonl"

    def append(self, msg: InterAgentMessage) -> None:
        """Append a single event; safe under concurrent writers (file lock optional)."""
        if not msg.scenario_id:
            raise ValueError("scenario_id is required")
        path = self._path_for(msg.scenario_id)
        line = json.dumps(msg.to_dict(), separators=(",", ":")) + "\n"
        with self._lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)

    def list_scenarios(self) -> List[str]:
        """Return scenario ids that have at least one recorded event."""
        out: List[str] = []
        if not self._root.is_dir():
            return out
        for p in self._root.iterdir():
            if p.is_file() and p.suffix == ".jsonl":
                out.append(p.stem)
        out.sort()
        return out

    def read(self, scenario_id: str) -> List[InterAgentMessage]:
        """Read all events for one scenario, in file order (append order)."""
        path = self._path_for(scenario_id)
        if not path.is_file():
            return []
        out: List[InterAgentMessage] = []
        with self._lock:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        out.append(InterAgentMessage.from_dict(json.loads(raw)))
                    except Exception:
                        continue
        return out

    def read_stitched(self, scenario_id: str) -> List[dict]:
        """Return one merged event per correlation_id.

        A completed call merges start + done (picking ts_start, ts_done,
        status, latency_ms from the done record). An in-flight call keeps
        just the start event with ts_done=None.
        """
        events = self.read(scenario_id)
        bucket: dict[str, dict] = {}
        order: list[str] = []
        for ev in events:
            cid = ev.correlation_id or ev.event_id
            slot = bucket.get(cid)
            if slot is None:
                slot = {
                    "correlation_id": cid,
                    "scenario_id": ev.scenario_id,
                    "from_host": ev.from_host,
                    "from_session": ev.from_session,
                    "to_host": ev.to_host,
                    "to_session": ev.to_session,
                    "kind": ev.kind,
                    "tool_name": ev.tool_name,
                    "payload_digest": ev.payload_digest,
                    "payload_preview": ev.payload_preview,
                    "ts_start": None,
                    "ts_done": None,
                    "status": "",
                    "latency_ms": 0.0,
                }
                bucket[cid] = slot
                order.append(cid)
            if ev.phase == "start":
                slot["ts_start"] = ev.ts
                # Start events seed routing / payload info if not yet set.
                for key in ("from_host", "from_session", "to_host",
                            "to_session", "kind", "tool_name",
                            "payload_digest", "payload_preview"):
                    if not slot[key]:
                        slot[key] = getattr(ev, key)
            else:  # done
                slot["ts_done"] = ev.ts
                slot["status"] = ev.status or "ok"
                slot["latency_ms"] = ev.latency_ms
                # Done events are authoritative for payload/digest if provided.
                for key in ("payload_digest", "payload_preview"):
                    v = getattr(ev, key)
                    if v:
                        slot[key] = v
        return [bucket[cid] for cid in order]


_DEFAULT_STORE: Optional[InterAgentStore] = None
_DEFAULT_LOCK = threading.Lock()


def get_store() -> InterAgentStore:
    """Process-wide singleton. First call creates the directory."""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_STORE is None:
                _DEFAULT_STORE = InterAgentStore()
    return _DEFAULT_STORE


def new_message(
    *,
    scenario_id: str,
    from_host: str,
    from_session: str,
    to_host: str,
    to_session: str,
    phase: str,
    correlation_id: str = "",
    kind: str = "mcp_call",
    tool_name: str = "",
    payload_preview: str = "",
    payload_digest: str = "",
    status: str = "",
    latency_ms: float = 0.0,
) -> InterAgentMessage:
    """Construct a new event with auto-generated event_id + timestamp."""
    return InterAgentMessage(
        event_id=uuid.uuid4().hex,
        scenario_id=scenario_id,
        correlation_id=correlation_id or uuid.uuid4().hex,
        phase=phase,
        from_host=from_host,
        from_session=from_session,
        to_host=to_host,
        to_session=to_session,
        ts=_iso_now(),
        kind=kind,
        tool_name=tool_name,
        payload_digest=payload_digest,
        payload_preview=payload_preview,
        status=status,
        latency_ms=latency_ms,
    )
