"""Event parser — converts a single JSONL line into a canonical Event."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class EventType(str, Enum):
    """Canonical event types derived from OpenClaw session logs."""

    USER_INPUT = "USER_INPUT"
    ASSISTANT = "ASSISTANT"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT_SUCCESS = "TOOL_RESULT_SUCCESS"
    TOOL_RESULT_ERROR = "TOOL_RESULT_ERROR"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class Event:
    """Normalised event produced by the parser."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    event_type: EventType = EventType.UNKNOWN
    severity: Severity = Severity.INFO
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    token_count: Optional[int] = None


def _detect_error(payload: Dict[str, Any]) -> bool:
    """Heuristic: look for error markers in a tool result."""
    msg = payload.get("message", {})
    content = msg.get("content", "")
    if isinstance(content, str):
        lowered = content.lower()
        return any(kw in lowered for kw in ("error", "exception", "traceback", "failed"))
    return False


def parse_line(line: str) -> Optional[Event]:
    """Parse a single JSON-Lines string into an :class:`Event`.

    Returns ``None`` when the line is blank or unparseable.
    """
    line = line.strip()
    if not line:
        return None

    try:
        data: Dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        return None

    # ── Determine event type from the JSON structure ───────────
    msg = data.get("message", {})
    role = msg.get("role", "").lower()
    record_type = data.get("type", "").lower()

    event_type = EventType.UNKNOWN
    severity = Severity.INFO

    if role == "user" or record_type == "user":
        event_type = EventType.USER_INPUT
    elif record_type in ("tool_call", "toolcall") or role == "toolcall":
        event_type = EventType.TOOL_CALL
    elif record_type in ("tool_result", "toolresult") or role == "toolresult":
        if _detect_error(data):
            event_type = EventType.TOOL_RESULT_ERROR
            severity = Severity.ERROR
        else:
            event_type = EventType.TOOL_RESULT_SUCCESS
    elif role == "assistant" or record_type == "assistant":
        event_type = EventType.ASSISTANT

    # ── Token count (if present) ───────────────────────────────
    usage = data.get("usage", {})
    token_count: Optional[int] = None
    if isinstance(usage, dict):
        token_count = usage.get("total_tokens") or usage.get("totalTokens")

    # ── Timestamp ──────────────────────────────────────────────
    ts_str = data.get("timestamp") or data.get("ts")
    if ts_str:
        try:
            ts = datetime.fromisoformat(str(ts_str))
        except (ValueError, TypeError):
            ts = datetime.now(timezone.utc)
    else:
        ts = datetime.now(timezone.utc)

    return Event(
        event_type=event_type,
        severity=severity,
        timestamp=ts,
        raw_payload=data,
        token_count=token_count,
    )
