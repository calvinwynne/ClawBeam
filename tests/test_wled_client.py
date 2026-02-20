"""Tests for the WLED client — uses a mock HTTP server to verify payloads."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import httpx
import pytest

from clawbeam.config import WledConfig
from clawbeam.wled_client import WledClient


# ── Fake transport that records requests ───────────────────────


class _RecordingTransport(httpx.AsyncBaseTransport):
    """In-process httpx transport that captures requests and returns 200."""

    def __init__(self, status: int = 200, fail_count: int = 0) -> None:
        self.recorded: List[Dict[str, Any]] = []
        self._status = status
        self._fail_count = fail_count
        self._call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._call_count += 1
        body = await request.aread()
        self.recorded.append({
            "method": request.method,
            "url": str(request.url),
            "body": json.loads(body) if body else None,
        })
        if self._call_count <= self._fail_count:
            raise httpx.ConnectError("simulated failure")
        return httpx.Response(self._status, json={"success": True})


# ── Helpers ────────────────────────────────────────────────────


def _make_client(transport: _RecordingTransport) -> WledClient:
    cfg = WledConfig(host="10.0.0.1", port=80)
    client = WledClient(cfg)
    # Replace internal httpx client with one using our transport
    client._client = httpx.AsyncClient(transport=transport)
    return client


# ── Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_state_sends_correct_payload() -> None:
    transport = _RecordingTransport()
    wled = _make_client(transport)

    payload = {"on": True, "bri": 128, "seg": [{"col": [[255, 0, 0]], "fx": 0}]}
    ok = await wled.apply_state(payload)

    assert ok is True
    assert len(transport.recorded) == 1
    assert transport.recorded[0]["body"] == payload
    assert "json/state" in transport.recorded[0]["url"]

    await wled.close()


@pytest.mark.asyncio
async def test_apply_preset() -> None:
    transport = _RecordingTransport()
    wled = _make_client(transport)

    ok = await wled.apply_preset(5)
    assert ok is True
    assert transport.recorded[0]["body"] == {"ps": 5}

    await wled.close()


@pytest.mark.asyncio
async def test_retries_on_failure() -> None:
    # First 2 calls fail, third succeeds
    transport = _RecordingTransport(fail_count=2)
    wled = _make_client(transport)
    wled.BACKOFF_BASE = 0.01  # speed up test

    ok = await wled.apply_state({"on": True})
    assert ok is True
    # Should have made 3 total attempts (2 failures + 1 success)
    assert len(transport.recorded) == 3

    await wled.close()


@pytest.mark.asyncio
async def test_all_retries_exhausted() -> None:
    transport = _RecordingTransport(fail_count=10)  # more than MAX_RETRIES
    wled = _make_client(transport)
    wled.BACKOFF_BASE = 0.01

    ok = await wled.apply_state({"on": True})
    assert ok is False
    assert not wled.healthy

    await wled.close()


@pytest.mark.asyncio
async def test_ping_healthy() -> None:
    transport = _RecordingTransport()
    wled = _make_client(transport)

    ok = await wled.ping()
    assert ok is True
    assert wled.healthy
    assert "json/info" in transport.recorded[0]["url"]

    await wled.close()
