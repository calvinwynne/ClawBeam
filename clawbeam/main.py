"""Main orchestrator — wires watcher, parser, state machine, and WLED client."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Optional

from .config import AppConfig, load_config
from .parser import parse_line
from .session_watcher import watch_sessions
from .state_machine import LampState, StateMachine
from .wled_client import WledClient

logger = logging.getLogger("clawbeam")


class Orchestrator:
    """Central controller that reads events and drives the WLED lamp."""

    def __init__(self, config: AppConfig) -> None:
        self._cfg = config
        self._stop = asyncio.Event()
        self._wled: Optional[WledClient] = None
        self._sm: Optional[StateMachine] = None

    async def run(self) -> None:
        """Main entry – runs until interrupted."""
        logging.basicConfig(
            level=getattr(logging, self._cfg.log_level.upper(), logging.INFO),
            format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        )

        self._wled = WledClient(self._cfg.wled)
        self._sm = StateMachine(
            self._cfg.state_machine,
            on_transition=self._on_transition,
        )

        # Start WLED health-check loop
        await self._wled.start_health_loop()

        # Set initial IDLE state on the lamp
        await self._apply_effect(LampState.IDLE)

        logger.info(
            "ClawBeam controller started — watching %s",
            self._cfg.watcher.sessions_dir,
        )

        try:
            async for line in watch_sessions(self._cfg.watcher, stop_event=self._stop):
                event = parse_line(line)
                if event is None:
                    continue
                logger.debug("Parsed event: %s  (type=%s)", event.id, event.event_type)
                await self._sm.handle_event(event)
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        logger.info("Shutting down …")
        if self._sm:
            self._sm.stop()
        if self._wled:
            await self._wled.close()

    async def _on_transition(self, old: LampState, new: LampState) -> None:
        """Called by the state machine on every real transition."""
        logger.info("Lamp: %s → %s", old.value, new.value)
        success = await self._apply_effect(new)
        if not success and self._sm:
            await self._sm.set_network_error()

    async def _apply_effect(self, state: LampState) -> bool:
        """Look up the WLED payload for *state* and POST it."""
        payload = self._cfg.state_effects.get(state.value)
        if not payload:
            logger.warning("No WLED effect configured for state %s", state.value)
            return True  # not a failure — just nothing to send
        if self._wled is None:
            return False
        return await self._wled.apply_state(payload)


def _register_signals(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass


def cli() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(
        prog="clawbeam",
        description="ClawBeam — OpenClaw → WLED real-time reactive lamp controller",
    )
    ap.add_argument(
        "-c", "--config",
        type=str,
        default=None,
        help="Path to config.yaml (default: $OPENCLAW_WLED_CONFIG or built-in defaults)",
    )
    ap.add_argument(
        "--one-shot",
        action="store_true",
        help="Process existing lines and exit (don't tail)",
    )
    ap.add_argument(
        "--log-level",
        type=str,
        default=None,
        help="Override log level (DEBUG, INFO, WARNING, ERROR)",
    )
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.log_level:
        cfg.log_level = args.log_level
    if args.one_shot:
        cfg.daemon = False

    orch = Orchestrator(cfg)

    if sys.platform != "win32":
        asyncio.run(_run_with_signals(orch))
    else:
        asyncio.run(orch.run())


async def _run_with_signals(orch: Orchestrator) -> None:
    _register_signals(orch._stop)
    await orch.run()


if __name__ == "__main__":
    cli()
