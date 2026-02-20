"""Tests for the JSON-line event parser."""

from __future__ import annotations

import json

import pytest

from clawbeam.parser import Event, EventType, Severity, parse_line


# ── Helpers ────────────────────────────────────────────────────


def _line(**kw: object) -> str:
    return json.dumps(kw)


# ── Tests ──────────────────────────────────────────────────────


class TestParseLineBasics:
    def test_blank_line_returns_none(self) -> None:
        assert parse_line("") is None
        assert parse_line("   ") is None

    def test_invalid_json_returns_none(self) -> None:
        assert parse_line("not json at all") is None

    def test_user_message(self) -> None:
        line = _line(type="user", message={"role": "user", "content": "hello"})
        event = parse_line(line)
        assert event is not None
        assert event.event_type == EventType.USER_INPUT

    def test_assistant_message(self) -> None:
        line = _line(type="assistant", message={"role": "assistant", "content": "thinking…"})
        event = parse_line(line)
        assert event is not None
        assert event.event_type == EventType.ASSISTANT

    def test_tool_call(self) -> None:
        line = _line(type="tool_call", message={"role": "toolCall", "content": "run ls"})
        event = parse_line(line)
        assert event is not None
        assert event.event_type == EventType.TOOL_CALL

    def test_tool_result_success(self) -> None:
        line = _line(type="tool_result", message={"role": "toolResult", "content": "ok done"})
        event = parse_line(line)
        assert event is not None
        assert event.event_type == EventType.TOOL_RESULT_SUCCESS
        assert event.severity == Severity.INFO

    def test_tool_result_error(self) -> None:
        line = _line(type="tool_result", message={"role": "toolResult", "content": "Error: file not found"})
        event = parse_line(line)
        assert event is not None
        assert event.event_type == EventType.TOOL_RESULT_ERROR
        assert event.severity == Severity.ERROR

    def test_unknown_type(self) -> None:
        line = _line(type="system", message={"role": "system", "content": "boot"})
        event = parse_line(line)
        assert event is not None
        assert event.event_type == EventType.UNKNOWN


class TestTokenCount:
    def test_token_count_from_usage(self) -> None:
        line = _line(type="assistant", message={"role": "assistant"}, usage={"total_tokens": 5000})
        event = parse_line(line)
        assert event is not None
        assert event.token_count == 5000

    def test_no_token_count(self) -> None:
        line = _line(type="assistant", message={"role": "assistant"})
        event = parse_line(line)
        assert event is not None
        assert event.token_count is None


class TestTimestamp:
    def test_iso_timestamp_parsed(self) -> None:
        line = _line(type="user", message={"role": "user"}, timestamp="2025-06-01T12:00:00+00:00")
        event = parse_line(line)
        assert event is not None
        assert event.timestamp.year == 2025

    def test_missing_timestamp_uses_utcnow(self) -> None:
        from datetime import datetime, timezone

        line = _line(type="user", message={"role": "user"})
        event = parse_line(line)
        assert event is not None
        assert (datetime.now(timezone.utc) - event.timestamp).total_seconds() < 5
