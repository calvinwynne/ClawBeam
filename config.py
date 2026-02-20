"""Configuration loader — reads YAML and applies sensible defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

import yaml


_DEFAULT_SESSIONS_DIR = Path.home() / ".openclaw" / "agents" / "main" / "sessions"


@dataclass
class WledConfig:
    """WLED lamp connection parameters."""

    host: str = "192.168.50.142"
    port: int = 80
    base_path: str = "/json"
    max_requests_per_sec: float = 5.0
    health_check_interval: float = 30.0
    connect_timeout: float = 5.0
    read_timeout: float = 5.0


@dataclass
class WatcherConfig:
    """Session directory watcher parameters."""

    sessions_dir: str = str(_DEFAULT_SESSIONS_DIR)
    poll_interval: float = 0.25  # seconds between tail reads
    watch_poll_interval: float = 1.0  # seconds between directory scans


@dataclass
class StateMachineConfig:
    """State machine timing."""

    min_state_duration: float = 0.5  # seconds — prevents flicker
    idle_timeout: float = 30.0  # seconds of silence → IDLE
    debounce_window: float = 0.5  # ignore duplicate transitions within this window


@dataclass
class AppConfig:
    """Top-level application configuration."""

    wled: WledConfig = field(default_factory=WledConfig)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)
    state_machine: StateMachineConfig = field(default_factory=StateMachineConfig)
    log_level: str = "INFO"
    daemon: bool = True

    # ── State→WLED preset mapping ──────────────────────────────────
    # Each value is a dict sent verbatim to the WLED JSON API.
    # If a preset id (ps) is set the lamp just recalls that preset.
    state_effects: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.state_effects:
            self.state_effects = _default_state_effects()


def _default_state_effects() -> Dict[str, Dict[str, Any]]:
    """Return the canonical state→WLED-payload mapping."""
    return {
        "IDLE": {
            "on": True,
            "bri": 80,
            "seg": [{"col": [[0, 60, 180]], "fx": 2, "sx": 80, "ix": 128}],
            # fx 2 = Breathe
        },
        "USER_INPUT": {
            "on": True,
            "bri": 255,
            "seg": [{"col": [[255, 255, 255]], "fx": 0, "sx": 0, "ix": 255}],
            "tt": 3,  # fast transition
        },
        "THINKING": {
            "on": True,
            "bri": 140,
            "seg": [{"col": [[130, 0, 200]], "fx": 2, "sx": 40, "ix": 200}],
        },
        "TOOL_CALL": {
            "on": True,
            "bri": 180,
            "seg": [{"col": [[0, 200, 200]], "fx": 9, "sx": 120, "ix": 180}],
            # fx 9 = Scan / sweep
        },
        "TOOL_SUCCESS": {
            "on": True,
            "bri": 220,
            "seg": [{"col": [[0, 220, 40]], "fx": 0, "sx": 0, "ix": 255}],
            "tt": 3,
        },
        "TOOL_ERROR": {
            "on": True,
            "bri": 255,
            "seg": [{"col": [[255, 0, 0]], "fx": 1, "sx": 200, "ix": 255}],
            # fx 1 = Blink
        },
        "NETWORK_ERROR": {
            "on": True,
            "bri": 200,
            "seg": [{"col": [[200, 0, 180]], "fx": 1, "sx": 160, "ix": 200}],
        },
        "HIGH_TOKENS": {
            "on": True,
            "bri": 160,
            "seg": [{"col": [[220, 160, 0]], "fx": 2, "sx": 60, "ix": 180}],
        },
    }


# ── YAML loader ────────────────────────────────────────────────────

def _merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (mutates base)."""
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _merge(base[key], val)
        else:
            base[key] = val
    return base


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load configuration from *path* (YAML), falling back to defaults.

    Environment variable ``OPENCLAW_WLED_CONFIG`` is checked when *path*
    is ``None``.
    """
    raw: Dict[str, Any] = {}

    if path is None:
        path = os.environ.get("CLAWBEAM_CONFIG")

    if path is not None:
        p = Path(path)
        if p.exists():
            with open(p, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}

    wled_kw = raw.get("wled", {})
    watcher_kw = raw.get("watcher", {})
    sm_kw = raw.get("state_machine", {})

    cfg = AppConfig(
        wled=WledConfig(**wled_kw),
        watcher=WatcherConfig(**watcher_kw),
        state_machine=StateMachineConfig(**sm_kw),
        log_level=raw.get("log_level", "INFO"),
        daemon=raw.get("daemon", True),
    )

    # Allow overriding individual state effects without losing defaults.
    if "state_effects" in raw:
        _merge(cfg.state_effects, raw["state_effects"])

    return cfg
