"""JSONL line → Event parser for OpenClaw session lines.

This module exposes `Event`, `EventType`, `Severity` and `parse_line()` which
match the small surface used by the test-suite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class EventType(Enum):
    USER_INPUT = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT_SUCCESS = "tool_result_success"
    TOOL_RESULT_ERROR = "tool_result_error"
    UNKNOWN = "unknown"


class Severity(Enum):
    INFO = "info"
    ERROR = "error"


@dataclass
class Event:
    id: str | None = None
    event_type: EventType = EventType.UNKNOWN
    message: Dict[str, Any] = None
    severity: Severity = Severity.INFO
    token_count: Optional[int] = None
    timestamp: datetime | None = None


def _map_type(type_str: str, message: Dict[str, Any]) -> (EventType, Severity):
    if not type_str:
        return EventType.UNKNOWN, Severity.INFO

    if type_str == "user":
        return EventType.USER_INPUT, Severity.INFO
    if type_str == "assistant":
        return EventType.ASSISTANT, Severity.INFO
    if type_str == "tool_call":
        return EventType.TOOL_CALL, Severity.INFO
    if type_str == "tool_result":
        # Heuristic: treat messages starting with "Error" (case-insensitive)
        content = (message or {}).get("content", "")
        if isinstance(content, str) and content.lower().startswith("error"):
            return EventType.TOOL_RESULT_ERROR, Severity.ERROR
        return EventType.TOOL_RESULT_SUCCESS, Severity.INFO

    return EventType.UNKNOWN, Severity.INFO


def parse_line(line: str) -> Optional[Event]:
    """Parse a single JSON-line from an OpenClaw session file.

    Returns None for blank/invalid input.
    """
    if not line or not line.strip():
        return None

    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None

    type_str = obj.get("type")
    message = obj.get("message", {}) or {}
    usage = obj.get("usage") or {}

    evt_type, severity = _map_type(type_str, message)

    ts = obj.get("timestamp")
    if ts:
        try:
            timestamp = datetime.fromisoformat(ts)
        except Exception:
            timestamp = datetime.now(timezone.utc)
    else:
        timestamp = datetime.now(timezone.utc)

    token_count = None
    if isinstance(usage, dict) and "total_tokens" in usage:
        try:
            token_count = int(usage["total_tokens"])
        except Exception:
            token_count = None

    evt_id = obj.get("id") or obj.get("timestamp") or None

    return Event(
        id=evt_id,
        event_type=evt_type,
        message=message,
        severity=severity,
        token_count=token_count,
        timestamp=timestamp,
    )
