"""Simulator — generates fake OpenClaw session events for testing without OpenClaw.

Usage
-----
Terminal 1:  clawbeam -c clawbeam/config.yaml --log-level DEBUG
Terminal 2:  python -m clawbeam.simulator

The simulator creates a .jsonl file in the sessions directory and appends
realistic events with pauses between them so you can watch the lamp react.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config

# ── Scripted scenario ──────────────────────────────────────────

SCENARIO: list[dict] = [
    {
        "type": "user",
        "message": {"role": "user", "content": "List all Python files in the project"},
        "delay": 1.0,
        "label": "USER_INPUT → white flash",
    },
    {
        "type": "assistant",
        "message": {"role": "assistant", "content": "I'll search for Python files in the project directory."},
        "delay": 2.0,
        "label": "THINKING → purple pulse",
    },
    {
        "type": "tool_call",
        "message": {"role": "toolCall", "content": "run_in_terminal: find . -name '*.py'"},
        "delay": 3.0,
        "label": "TOOL_CALL → cyan sweep",
    },
    {
        "type": "tool_result",
        "message": {"role": "toolResult", "content": "./main.py\n./config.py\n./parser.py"},
        "delay": 1.5,
        "label": "TOOL_SUCCESS → green flash",
    },
    {
        "type": "assistant",
        "message": {"role": "assistant", "content": "I found 3 Python files in the project."},
        "delay": 2.0,
        "label": "THINKING → purple pulse",
    },
    {
        "type": "user",
        "message": {"role": "user", "content": "Delete the temporary files"},
        "delay": 1.0,
        "label": "USER_INPUT → white flash",
    },
    {
        "type": "tool_call",
        "message": {"role": "toolCall", "content": "run_in_terminal: rm -rf /tmp/build"},
        "delay": 2.5,
        "label": "TOOL_CALL → cyan sweep",
    },
    {
        "type": "tool_result",
        "message": {"role": "toolResult", "content": "Error: Permission denied - cannot remove /tmp/build"},
        "delay": 2.0,
        "label": "TOOL_ERROR → red blink",
    },
    {
        "type": "assistant",
        "message": {"role": "assistant", "content": "The deletion failed due to permissions. Let me try with elevated privileges..."},
        "usage": {"total_tokens": 5500},
        "delay": 3.0,
        "label": "HIGH_TOKENS → amber pulse (5500 tokens)",
    },
    {
        "type": "tool_call",
        "message": {"role": "toolCall", "content": "run_in_terminal: sudo rm -rf /tmp/build"},
        "delay": 2.0,
        "label": "TOOL_CALL → cyan sweep",
    },
    {
        "type": "tool_result",
        "message": {"role": "toolResult", "content": "Directory removed successfully."},
        "delay": 1.5,
        "label": "TOOL_SUCCESS → green flash",
    },
    {
        "type": "assistant",
        "message": {"role": "assistant", "content": "Done! The temporary files have been cleaned up."},
        "delay": 0,
        "label": "THINKING → purple pulse … then IDLE after timeout",
    },
]


def _make_line(entry: dict) -> str:
    payload = {
        "type": entry["type"],
        "message": entry["message"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if "usage" in entry:
        payload["usage"] = entry["usage"]
    return json.dumps(payload)


def run_scenario(
    sessions_dir: Path,
    *,
    loops: int = 1,
    speed: float = 1.0,
) -> None:
    sessions_dir.mkdir(parents=True, exist_ok=True)

    filename = f"sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    filepath = sessions_dir / filename

    print(f"╔══════════════════════════════════════════════════════╗")
    print(f"║  ClawBeam Simulator                                 ║")
    print(f"╠══════════════════════════════════════════════════════╣")
    print(f"║  Session file: {filepath}")
    print(f"║  Speed:        {speed}x")
    print(f"║  Loops:        {loops}")
    print(f"╚══════════════════════════════════════════════════════╝")
    print()
    print("Make sure the ClawBeam controller is running in another terminal:")
    print(f"  clawbeam -c clawbeam/config.yaml --log-level DEBUG")
    print()
    print("─── Starting in 3 seconds … ───")
    time.sleep(3)

    for loop_num in range(1, loops + 1):
        if loops > 1:
            print(f"\n═══ Loop {loop_num}/{loops} ═══")

        for i, entry in enumerate(SCENARIO, 1):
            line = _make_line(entry)
            label = entry.get("label", entry["type"])
            delay = entry.get("delay", 1.0) / speed

            print(f"  [{i:2d}/{len(SCENARIO)}]  {label}")

            with open(filepath, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()

            if delay > 0:
                time.sleep(delay)

    print()
    print("✓ Scenario complete.  Lamp should return to IDLE after the idle timeout.")
    print(f"  Session file: {filepath}")


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="clawbeam-sim",
        description="ClawBeam simulator — generate fake OpenClaw events to test the lamp",
    )
    ap.add_argument(
        "-c", "--config",
        type=str,
        default=None,
        help="Path to config.yaml (uses same config as the controller)",
    )
    ap.add_argument(
        "-d", "--sessions-dir",
        type=str,
        default=None,
        help="Override sessions directory (default: from config)",
    )
    ap.add_argument(
        "--loops",
        type=int,
        default=1,
        help="Number of times to repeat the scenario (default: 1)",
    )
    ap.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speed multiplier — 2.0 = twice as fast, 0.5 = half speed (default: 1.0)",
    )
    args = ap.parse_args()

    cfg = load_config(args.config)

    sessions_dir = Path(args.sessions_dir) if args.sessions_dir else Path(cfg.watcher.sessions_dir)

    run_scenario(sessions_dir, loops=args.loops, speed=args.speed)


if __name__ == "__main__":
    main()
