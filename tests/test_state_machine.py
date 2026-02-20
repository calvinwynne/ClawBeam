"""Tests for the state machine."""

from __future__ import annotations

import asyncio
from typing import List, Tuple

import pytest

from clawbeam.config import StateMachineConfig
from clawbeam.parser import Event, EventType
from clawbeam.state_machine import LampState, StateMachine


@pytest.mark.asyncio
async def test_user_input_transitions_from_idle() -> None:
    transitions: List[Tuple[LampState, LampState]] = []

    async def _cb(old: LampState, new: LampState) -> None:
        transitions.append((old, new))

    sm = StateMachine(StateMachineConfig(min_state_duration=0.0, debounce_window=0.0), on_transition=_cb)
    assert sm.state == LampState.IDLE

    evt = Event(event_type=EventType.USER_INPUT)
    await sm.handle_event(evt)

    assert sm.state == LampState.USER_INPUT
    assert transitions == [(LampState.IDLE, LampState.USER_INPUT)]
    sm.stop()


@pytest.mark.asyncio
async def test_min_duration_prevents_flicker() -> None:
    transitions: List[Tuple[LampState, LampState]] = []

    async def _cb(old: LampState, new: LampState) -> None:
        transitions.append((old, new))

    sm = StateMachine(StateMachineConfig(min_state_duration=10.0, debounce_window=0.0), on_transition=_cb)

    # Allow the initial IDLE state to be left (set entered_at far in the past)
    sm._state_entered_at = 0.0

    # First event should transition
    await sm.handle_event(Event(event_type=EventType.USER_INPUT))
    assert sm.state == LampState.USER_INPUT

    # Second event immediately after should be blocked by min_state_duration
    await sm.handle_event(Event(event_type=EventType.ASSISTANT))

    assert sm.state == LampState.USER_INPUT  # still stuck
    assert len(transitions) == 1
    sm.stop()


@pytest.mark.asyncio
async def test_debounce_suppresses_duplicate() -> None:
    transitions: List[Tuple[LampState, LampState]] = []

    async def _cb(old: LampState, new: LampState) -> None:
        transitions.append((old, new))

    sm = StateMachine(StateMachineConfig(min_state_duration=0.0, debounce_window=5.0), on_transition=_cb)

    await sm.handle_event(Event(event_type=EventType.USER_INPUT))
    # Force state back to idle manually to test debounce of same key
    sm._state = LampState.IDLE
    sm._state_entered_at = 0
    await sm.handle_event(Event(event_type=EventType.USER_INPUT))

    # The IDLE→USER_INPUT key was fired within debounce window, so second should be suppressed
    assert len(transitions) == 1
    sm.stop()


@pytest.mark.asyncio
async def test_idle_timeout() -> None:
    transitions: List[Tuple[LampState, LampState]] = []

    async def _cb(old: LampState, new: LampState) -> None:
        transitions.append((old, new))

    sm = StateMachine(
        StateMachineConfig(min_state_duration=0.0, idle_timeout=0.2, debounce_window=0.0),
        on_transition=_cb,
    )

    await sm.handle_event(Event(event_type=EventType.USER_INPUT))
    assert sm.state == LampState.USER_INPUT

    # Wait for idle timeout to fire
    await asyncio.sleep(0.4)

    assert sm.state == LampState.IDLE
    sm.stop()


@pytest.mark.asyncio
async def test_network_error_and_recovery() -> None:
    sm = StateMachine(StateMachineConfig(min_state_duration=0.0, debounce_window=0.0))

    await sm.set_network_error()
    assert sm.state == LampState.NETWORK_ERROR

    await sm.clear_network_error()
    assert sm.state == LampState.IDLE
    sm.stop()
