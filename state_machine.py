"""State machine — maps parsed events to lamp states with timing guards."""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Callable, Optional, Awaitable

from .config import StateMachineConfig
from .parser import Event, EventType

logger = logging.getLogger(__name__)


class LampState(str, Enum):
    """Logical states the lamp can be in."""

    IDLE = "IDLE"
    USER_INPUT = "USER_INPUT"
    THINKING = "THINKING"
    TOOL_CALL = "TOOL_CALL"
    TOOL_SUCCESS = "TOOL_SUCCESS"
    TOOL_ERROR = "TOOL_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    HIGH_TOKENS = "HIGH_TOKENS"


# ── Event → target-state mapping ──────────────────────────────────

_EVENT_TO_STATE = {
    EventType.USER_INPUT: LampState.USER_INPUT,
    EventType.ASSISTANT: LampState.THINKING,
    EventType.TOOL_CALL: LampState.TOOL_CALL,
    EventType.TOOL_RESULT_SUCCESS: LampState.TOOL_SUCCESS,
    EventType.TOOL_RESULT_ERROR: LampState.TOOL_ERROR,
}

HIGH_TOKEN_THRESHOLD = 4000  # tokens


class StateMachine:
    """Manages lamp state transitions with debounce, min-duration, and idle timeout.

    Parameters
    ----------
    config:
        Timing configuration.
    on_transition:
        Async callback invoked with ``(old_state, new_state)`` whenever a
        real transition fires.
    """

    def __init__(
        self,
        config: StateMachineConfig,
        on_transition: Optional[Callable[[LampState, LampState], Awaitable[None]]] = None,
    ) -> None:
        self._cfg = config
        self._on_transition = on_transition

        self._state: LampState = LampState.IDLE
        self._state_entered_at: float = time.monotonic()
        self._last_activity: float = time.monotonic()
        self._last_transition_key: Optional[str] = None
        self._last_transition_time: float = 0.0

        self._idle_task: Optional[asyncio.Task[None]] = None

    # ── Public API ─────────────────────────────────────────────

    @property
    def state(self) -> LampState:
        return self._state

    async def handle_event(self, event: Event) -> None:
        """Process *event* and potentially transition state."""
        self._last_activity = time.monotonic()
        self._restart_idle_timer()

        # Determine target state
        target = _EVENT_TO_STATE.get(event.event_type)

        # Override: very high token count → amber pulse
        if event.token_count and event.token_count >= HIGH_TOKEN_THRESHOLD:
            target = LampState.HIGH_TOKENS

        if target is None:
            return

        await self._try_transition(target)

    async def set_network_error(self) -> None:
        """Force NETWORK_ERROR state (called by wled_client on HTTP failure)."""
        await self._try_transition(LampState.NETWORK_ERROR)

    async def clear_network_error(self) -> None:
        """Recover from NETWORK_ERROR back to IDLE."""
        if self._state == LampState.NETWORK_ERROR:
            await self._try_transition(LampState.IDLE)

    # ── Internals ──────────────────────────────────────────────

    async def _try_transition(self, target: LampState) -> None:
        now = time.monotonic()

        # Enforce minimum state duration (anti-flicker)
        if now - self._state_entered_at < self._cfg.min_state_duration:
            return

        # Debounce duplicate transitions
        key = f"{self._state}->{target}"
        if key == self._last_transition_key and (now - self._last_transition_time) < self._cfg.debounce_window:
            return

        if target == self._state:
            return

        old = self._state
        self._state = target
        self._state_entered_at = now
        self._last_transition_key = key
        self._last_transition_time = now

        logger.info("State transition: %s → %s", old, target)

        if self._on_transition:
            try:
                await self._on_transition(old, target)
            except Exception:
                logger.exception("on_transition callback failed")

    # ── Idle timeout ───────────────────────────────────────────

    def _restart_idle_timer(self) -> None:
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = asyncio.ensure_future(self._idle_watcher())

    async def _idle_watcher(self) -> None:
        try:
            await asyncio.sleep(self._cfg.idle_timeout)
            # If still no new activity, revert to idle
            if time.monotonic() - self._last_activity >= self._cfg.idle_timeout:
                await self._try_transition(LampState.IDLE)
        except asyncio.CancelledError:
            pass

    def stop(self) -> None:
        """Cancel background tasks."""
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
