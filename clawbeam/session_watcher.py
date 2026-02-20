
"""Line-tail utilities used by the controller and tests.

Provides `tail_file()` (async generator that seeks-to-end and yields appended
lines) and `_latest_session()` which selects the newest session file while
ignoring reset files.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncIterator, Optional


async def tail_file(path: Path, *, poll_interval: float = 0.05, stop_event: asyncio.Event) -> AsyncIterator[str]:
    """Async generator that yields lines appended to *path*.

    The file is opened and seeked to the end, then newly appended data is
    buffered until a full newline is available. Partial writes are supported.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Ensure file exists
    path.touch(exist_ok=True)

    with open(path, "r", encoding="utf-8") as fh:
        fh.seek(0, os.SEEK_END)
        buffer = ""
        while not stop_event.is_set():
            chunk = fh.read()
            if not chunk:
                await asyncio.sleep(poll_interval)
                continue
            buffer += chunk
            while True:
                idx = buffer.find("\n")
                if idx == -1:
                    break
                line = buffer[:idx]
                buffer = buffer[idx + 1 :]
                yield line


def _latest_session(sessions_dir: Path) -> Optional[Path]:
    """Return the newest `.jsonl` file in *sessions_dir*, ignoring reset files.

    Files with `-reset` in the name are ignored.
    """
    sessions_dir.mkdir(parents=True, exist_ok=True)
    files = [p for p in sessions_dir.glob("*.jsonl") if "-reset" not in p.name]
    if not files:
        return None
    # Pick by modification time (newest)
    files.sort(key=lambda p: p.stat().st_mtime)
    return files[-1]


async def watch_sessions(cfg, *, stop_event: asyncio.Event) -> AsyncIterator[str]:
    """Watch the sessions directory and yield new lines from the latest file.

    This mirrors the original behaviour expected by the controller: pick the
    newest session `.jsonl`, seek to its end, then yield appended lines until a
    newer session file appears.
    """
    sessions_dir = Path(cfg.sessions_dir)
    sessions_dir.mkdir(parents=True, exist_ok=True)

    latest: Optional[Path] = None
    fh = None
    try:
        while not stop_event.is_set():
            cand = _latest_session(sessions_dir)
            if cand and cand != latest:
                if fh:
                    fh.close()
                latest = cand
                fh = open(latest, "r", encoding="utf-8")
                fh.seek(0, os.SEEK_END)

            if fh:
                line = fh.readline()
                if line:
                    yield line.rstrip("\n")
                else:
                    await asyncio.sleep(getattr(cfg, "poll_interval", 0.25))
            else:
                await asyncio.sleep(getattr(cfg, "watch_poll_interval", 1.0))
    finally:
        if fh:
            fh.close()

