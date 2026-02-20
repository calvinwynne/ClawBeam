"""Tests for the line-tailing logic in session_watcher."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from clawbeam.session_watcher import tail_file, _latest_session


# ── tail_file ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tail_file_yields_new_lines(tmp_path: Path) -> None:
    """Lines appended after seek-to-end are yielded one at a time."""
    log = tmp_path / "session.jsonl"
    log.write_text("")  # start empty

    stop = asyncio.Event()
    collected: list[str] = []

    async def _reader() -> None:
        async for line in tail_file(log, poll_interval=0.05, stop_event=stop):
            collected.append(line)
            if len(collected) >= 3:
                stop.set()

    reader_task = asyncio.create_task(_reader())

    # Simulate appending lines with small delays
    await asyncio.sleep(0.1)
    with open(log, "a", encoding="utf-8") as fh:
        for i in range(3):
            fh.write(f'{{"seq": {i}}}\n')
            fh.flush()
            await asyncio.sleep(0.08)

    await asyncio.wait_for(reader_task, timeout=5.0)

    assert len(collected) == 3
    assert collected[0] == '{"seq": 0}'


@pytest.mark.asyncio
async def test_tail_file_handles_partial_writes(tmp_path: Path) -> None:
    """Partial lines (no trailing newline) are buffered until complete."""
    log = tmp_path / "session.jsonl"
    log.write_text("")

    stop = asyncio.Event()
    collected: list[str] = []

    async def _reader() -> None:
        async for line in tail_file(log, poll_interval=0.05, stop_event=stop):
            collected.append(line)
            if len(collected) >= 1:
                stop.set()

    reader_task = asyncio.create_task(_reader())
    await asyncio.sleep(0.1)

    with open(log, "a", encoding="utf-8") as fh:
        fh.write('{"part')
        fh.flush()
        await asyncio.sleep(0.15)
        fh.write('ial": true}\n')
        fh.flush()

    await asyncio.wait_for(reader_task, timeout=5.0)
    assert collected == ['{"partial": true}']


# ── _latest_session ────────────────────────────────────────────


def test_latest_session_picks_newest(tmp_path: Path) -> None:
    import time

    old = tmp_path / "old.jsonl"
    old.write_text("{}\n")
    time.sleep(0.05)

    new = tmp_path / "new.jsonl"
    new.write_text("{}\n")

    assert _latest_session(tmp_path) == new


def test_latest_session_ignores_reset_files(tmp_path: Path) -> None:
    import time

    good = tmp_path / "session1.jsonl"
    good.write_text("{}\n")
    time.sleep(0.05)

    reset = tmp_path / "session1-reset.jsonl"
    reset.write_text("{}\n")

    assert _latest_session(tmp_path) == good
