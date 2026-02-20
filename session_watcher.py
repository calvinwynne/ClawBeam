"""Session watcher — finds the active .jsonl and tails it in real-time."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import AsyncIterator, Optional

from .config import WatcherConfig

logger = logging.getLogger(__name__)


def _latest_session(sessions_dir: Path) -> Optional[Path]:
    """Return the most-recently-modified .jsonl file, skipping *-reset* files."""
    candidates = [
        p
        for p in sessions_dir.glob("*.jsonl")
        if "reset" not in p.stem.lower()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


async def tail_file(
    path: Path,
    poll_interval: float = 0.25,
    *,
    stop_event: Optional[asyncio.Event] = None,
) -> AsyncIterator[str]:
    """Yield new complete lines as they are appended to *path*.

    Seeks to end-of-file on start, then polls for new data.  Handles
    partial writes by only yielding lines that end with ``\\n``.
    """
    logger.info("Tailing file: %s", path)
    buffer = ""

    with open(path, "r", encoding="utf-8") as fh:
        # Jump to end
        fh.seek(0, os.SEEK_END)

        while True:
            if stop_event and stop_event.is_set():
                return

            chunk = fh.read()
            if chunk:
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    yield line
            else:
                await asyncio.sleep(poll_interval)


async def watch_sessions(
    config: WatcherConfig,
    *,
    stop_event: Optional[asyncio.Event] = None,
) -> AsyncIterator[str]:
    """Watch the sessions directory and yield lines from the active file.

    Automatically switches to a newer file when one appears.
    """
    sessions_dir = Path(config.sessions_dir)

    if not sessions_dir.exists():
        logger.warning("Sessions directory does not exist yet: %s — waiting …", sessions_dir)
        while not sessions_dir.exists():
            if stop_event and stop_event.is_set():
                return
            await asyncio.sleep(config.watch_poll_interval)

    current_path: Optional[Path] = None

    while True:
        if stop_event and stop_event.is_set():
            return

        latest = _latest_session(sessions_dir)

        if latest is None:
            logger.debug("No session files found in %s; waiting …", sessions_dir)
            await asyncio.sleep(config.watch_poll_interval)
            continue

        if latest != current_path:
            if current_path is not None:
                logger.info("Switching session file: %s → %s", current_path.name, latest.name)
            current_path = latest

        # Tail the current file; break out when a newer file appears.
        inner_stop = asyncio.Event()

        async def _check_newer() -> None:
            """Background coroutine that sets *inner_stop* when a newer file exists."""
            while not inner_stop.is_set():
                await asyncio.sleep(config.watch_poll_interval)
                if stop_event and stop_event.is_set():
                    inner_stop.set()
                    return
                newest = _latest_session(sessions_dir)
                if newest and newest != current_path:
                    logger.debug("Newer session detected: %s", newest.name)
                    inner_stop.set()

        checker = asyncio.ensure_future(_check_newer())

        try:
            async for line in tail_file(current_path, config.poll_interval, stop_event=inner_stop):
                yield line
        finally:
            checker.cancel()
            try:
                await checker
            except asyncio.CancelledError:
                pass
