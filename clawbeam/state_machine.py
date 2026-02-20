"""Event → LampState state machine with timers and debounce.

This implementation provides the behavior exercised by the unit tests: min
state duration (anti-flicker), a debounce window for suppressing duplicate
transitions, an idle-timeout task that returns the lamp to `IDLE`, and simple
network-error handling.
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Callable, Dict, Optional

from .parser import EventType


class LampState(Enum):
    IDLE = "IDLE"
    USER_INPUT = "USER_INPUT"
    THINKING = "THINKING"
    TOOL_CALL = "TOOL_CALL"
    TOOL_SUCCESS = "TOOL_SUCCESS"
    TOOL_ERROR = "TOOL_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    HIGH_TOKENS = "HIGH_TOKENS"


class StateMachine:
    def __init__(self, cfg, on_transition: Optional[Callable[[LampState, LampState], None]] = None):
        # cfg can be an instance of clawbeam.config.StateMachineConfig
        self._cfg = cfg
        self._on_transition = on_transition

        self._state: LampState = LampState.IDLE
        self._state_entered_at: float = time.monotonic()

        # Track last time a specific (old->new) key fired for debounce.
        self._last_transition_times: Dict[tuple, float] = {}

        # Idle timer
        self._idle_task: Optional[asyncio.Task[None]] = None

        # Lock for concurrent events
        self._lock = asyncio.Lock()

    @property
    def state(self) -> LampState:
        return self._state

    async def _do_transition(self, new: LampState) -> None:
        old = self._state
        if old == new:
            return

        now = time.monotonic()

        # min_state_duration prevents leaving too quickly
        min_dur = getattr(self._cfg, "min_state_duration", 0.0)
        if now - self._state_entered_at < min_dur:
            return

        # debounce: suppress repeated identical transitions within window
        key = (old, new)
        debounce_window = getattr(self._cfg, "debounce_window", 0.0)
        last = self._last_transition_times.get(key)
        if last is not None and (now - last) < debounce_window:
            return

        # perform transition
        self._state = new
        self._state_entered_at = now
        self._last_transition_times[key] = now

        # reset idle timer when leaving IDLE
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None

        if new != LampState.IDLE and getattr(self._cfg, "idle_timeout", None):
            self._idle_task = asyncio.create_task(self._idle_watcher(new))

        if self._on_transition:
            await self._on_transition(old, new)

    async def handle_event(self, event) -> None:
        # Map EventType → LampState
        mapping = {
            EventType.USER_INPUT: LampState.USER_INPUT,
            EventType.ASSISTANT: LampState.THINKING,
            EventType.TOOL_CALL: LampState.TOOL_CALL,
            EventType.TOOL_RESULT_SUCCESS: LampState.TOOL_SUCCESS,
            EventType.TOOL_RESULT_ERROR: LampState.TOOL_ERROR,
        }

        new = mapping.get(event.event_type, LampState.IDLE)

        async with self._lock:
            await self._do_transition(new)

    async def _idle_watcher(self, watched_state: LampState) -> None:
        try:
            timeout = getattr(self._cfg, "idle_timeout", None)
            if not timeout:
                return
            await asyncio.sleep(timeout)
            # If still in the watched state (no newer transitions) switch to IDLE
            if self._state == watched_state:
                async with self._lock:
                    await self._do_transition(LampState.IDLE)
        except asyncio.CancelledError:
            return

    def stop(self) -> None:
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()

    async def set_network_error(self) -> None:
        async with self._lock:
            await self._do_transition(LampState.NETWORK_ERROR)

    async def clear_network_error(self) -> None:
        async with self._lock:
            await self._do_transition(LampState.IDLE)

