"""WLED async HTTP client — drives the lamp via the WLED JSON API."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

import httpx

from .config import WledConfig

logger = logging.getLogger(__name__)


class WledClient:
    """Async client for a single WLED device.

    Features
    --------
    * Rate-limiting (token-bucket style).
    * Automatic retries with exponential back-off.
    * Periodic health-check pings.
    * Graceful close.

    Parameters
    ----------
    config:
        WLED connection settings.
    """

    MAX_RETRIES = 3
    BACKOFF_BASE = 1.0  # seconds

    def __init__(self, config: WledConfig) -> None:
        self._cfg = config
        self._base_url = f"http://{config.host}:{config.port}"
        self._state_url = f"{self._base_url}{config.base_path}/state"
        self._info_url = f"{self._base_url}{config.base_path}/info"

        timeout = httpx.Timeout(
            connect=config.connect_timeout,
            read=config.read_timeout,
            write=config.read_timeout,
            pool=config.connect_timeout,
        )
        self._client = httpx.AsyncClient(timeout=timeout)

        # Rate-limiting state
        self._min_interval = 1.0 / config.max_requests_per_sec
        self._last_request_time: float = 0.0
        self._rate_lock = asyncio.Lock()

        # Health-check
        self._health_task: Optional[asyncio.Task[None]] = None
        self._healthy: bool = True

    @property
    def healthy(self) -> bool:
        return self._healthy

    async def apply_state(self, payload: Dict[str, Any]) -> bool:
        """POST *payload* to the WLED ``/json/state`` endpoint.

        Returns ``True`` on success, ``False`` on failure after retries.
        """
        return await self._post(self._state_url, payload)

    async def apply_preset(self, preset_id: int) -> bool:
        """Recall a WLED preset by id."""
        return await self.apply_state({"ps": preset_id})

    async def ping(self) -> bool:
        """Quick health check against ``/json/info``."""
        try:
            await self._rate_limit()
            resp = await self._client.get(self._info_url)
            ok = resp.status_code == 200
            self._healthy = ok
            return ok
        except (httpx.HTTPError, OSError):
            self._healthy = False
            return False

    async def start_health_loop(self) -> None:
        """Start a background health-check loop."""
        self._health_task = asyncio.ensure_future(self._health_loop())

    async def close(self) -> None:
        """Shut down the client and cancel background tasks."""
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        await self._client.aclose()

    async def _rate_limit(self) -> None:
        """Enforce max requests/sec with a simple token-bucket approach."""
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_time = time.monotonic()

    async def _post(self, url: str, payload: Dict[str, Any]) -> bool:
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                await self._rate_limit()
                resp = await self._client.post(url, json=payload)
                if resp.status_code == 200:
                    self._healthy = True
                    logger.debug("WLED POST %s → 200", url)
                    return True
                logger.warning("WLED POST %s → %s (attempt %d)", url, resp.status_code, attempt)
            except (httpx.HTTPError, OSError) as exc:
                logger.warning("WLED POST %s failed: %s (attempt %d)", url, exc, attempt)

            # Back-off
            if attempt < self.MAX_RETRIES:
                delay = self.BACKOFF_BASE * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        self._healthy = False
        logger.error("WLED POST %s: all %d attempts exhausted", url, self.MAX_RETRIES)
        return False

    async def _health_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._cfg.health_check_interval)
                ok = await self.ping()
                if ok:
                    logger.debug("WLED health check: OK")
                else:
                    logger.warning("WLED health check: FAIL")
        except asyncio.CancelledError:
            pass
