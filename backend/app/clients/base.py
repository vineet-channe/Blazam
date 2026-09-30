"""Shared HTTP plumbing for all third-party clients.

Features: per-request timeout, bounded retries with exponential backoff (+ ``Retry-After``),
per-client minimum request interval (throttle), on-disk response cache, and graceful
degradation (callers get ``None`` instead of an exception on upstream failure).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

from app.config import SETTINGS

log = logging.getLogger("blazam.clients")

Sleep = Callable[[float], Awaitable[None]]


class Cache(Protocol):
    def cache_get(self, key: str) -> Any | None: ...
    def cache_set(self, key: str, value: Any, ttl_s: float | None) -> None: ...


class NullCache:
    def cache_get(self, key: str) -> Any | None:
        return None

    def cache_set(self, key: str, value: Any, ttl_s: float | None) -> None:
        return None


class UpstreamError(RuntimeError):
    """Non-retryable upstream failure (after retries were exhausted or on a 4xx)."""


class Retryable(Exception):
    """Raised inside a response check to request a retry (e.g. Deezer quota code 4)."""

    def __init__(self, msg: str, retry_after: float | None = None) -> None:
        super().__init__(msg)
        self.retry_after = retry_after


class BaseClient:
    """Base async client. Subclasses set ``name``, ``base_url`` and ``min_interval_s``."""

    name = "base"
    base_url = ""
    min_interval_s = 0.0
    cache_ttl_s: float | None = 24 * 3600

    def __init__(
        self,
        *,
        cache: Cache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float | None = None,
        retries: int | None = None,
        backoff_base_s: float = 0.5,
        sleep: Sleep | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.cache: Cache = cache or NullCache()
        self.retries = SETTINGS.http_retries if retries is None else retries
        self.backoff_base_s = backoff_base_s
        self._sleep: Sleep = sleep or asyncio.sleep
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_s or SETTINGS.http_timeout_s,
            transport=transport,
            headers={"User-Agent": user_agent or SETTINGS.user_agent, "Accept": "application/json"},
            follow_redirects=False,
        )
        self._throttle_lock = asyncio.Lock()
        self._last_request = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ internals
    async def _throttle(self) -> None:
        if self.min_interval_s <= 0:
            return
        async with self._throttle_lock:
            wait = self._last_request + self.min_interval_s - time.monotonic()
            if wait > 0:
                await self._sleep(wait)
            self._last_request = time.monotonic()

    def _cache_key(self, method: str, url: str, params: dict | None) -> str:
        raw = json.dumps([self.name, method, url, sorted((params or {}).items())], default=str)
        return f"{self.name}:{hashlib.sha1(raw.encode()).hexdigest()}"

    def check(self, resp: httpx.Response) -> Any:
        """Validate a response and return its parsed payload. Override per API.

        Raise :class:`Retryable` to retry, :class:`UpstreamError` to give up.
        Return ``None`` for a legitimate "not found".
        """
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        use_cache: bool = True,
        ttl_s: float | None = None,
    ) -> Any:
        """Perform a request with cache, throttle, retries and backoff.

        Returns the value from :meth:`check` (``None`` for not-found).
        Raises :class:`UpstreamError` when all attempts fail.
        """
        cacheable = use_cache and method in ("GET", "HEAD")
        key = self._cache_key(method, url, params) if cacheable else ""
        if cacheable:
            hit = self.cache.cache_get(key)
            if hit is not None:
                return hit.get("v")
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            await self._throttle()
            retry_after: float | None = None
            try:
                resp = await self._client.request(method, url, params=params, data=data, files=files)
                if resp.status_code == 429 or resp.status_code >= 500:
                    ra = resp.headers.get("Retry-After")
                    retry_after = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
                    raise Retryable(f"HTTP {resp.status_code}", retry_after)
                value = self.check(resp)
                if cacheable:
                    self.cache.cache_set(key, {"v": value}, ttl_s if ttl_s is not None else self.cache_ttl_s)
                return value
            except Retryable as e:
                last_err, retry_after = e, e.retry_after
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_err = e
            except httpx.HTTPStatusError as e:  # other 4xx: not retryable
                raise UpstreamError(f"{self.name}: HTTP {e.response.status_code}") from e
            except (ValueError, json.JSONDecodeError) as e:
                raise UpstreamError(f"{self.name}: invalid response body: {e}") from e
            if attempt < self.retries:
                delay = retry_after if retry_after is not None else self.backoff_base_s * (2**attempt)
                log.warning("%s: attempt %d failed (%s); retrying in %.2fs", self.name, attempt + 1, last_err, delay)
                await self._sleep(delay)
        raise UpstreamError(f"{self.name}: giving up after {self.retries + 1} attempts: {last_err}")

    async def safe(self, coro: Awaitable[Any], default: Any = None) -> Any:
        """Await ``coro`` and convert any upstream failure into ``default`` (graceful degradation)."""
        try:
            return await coro
        except (UpstreamError, httpx.HTTPError) as e:
            log.warning("%s unavailable: %s", self.name, e)
            return default
