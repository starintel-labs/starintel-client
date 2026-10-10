"""Thin HTTP transport primitives: bounded timeouts, conservative retry.

Effects live here; everything above (registry parsing, envelope mapping,
correlation ids) is deterministic and testable without sockets.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from starintel_canonical import parse_json, stringify_json

from ._errors import StarIntelConnectionError, error_from_payload

__all__ = [
    "AsyncTransport",
    "RetryPolicy",
    "SyncTransport",
    "TransportResponse",
    "should_retry",
    "timeout_for",
]

MAX_TIMEOUT_SECONDS = 120.0
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
_RETRYABLE_STATUSES = frozenset({502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    """Conservative retry: idempotent GETs only, bounded attempts."""

    max_retries: int = 2
    backoff_seconds: tuple[float, ...] = (0.05, 0.2)

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if len(self.backoff_seconds) < self.max_retries:
            raise ValueError("backoff_seconds must cover max_retries attempts")


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes


def should_retry(
    method: str,
    status_code: int | None,
    attempt: int,
    policy: RetryPolicy,
) -> bool:
    """Decide one retry for a request attempt.

    ``status_code is None`` marks a transport-level failure. Only idempotent
    GET requests are retried, and never 4xx (nor 5xx outside the small
    retryable set).
    """
    if method.upper() != "GET" or attempt >= policy.max_retries:
        return False
    return status_code is None or status_code in _RETRYABLE_STATUSES


def timeout_for(timeout: float | None) -> httpx.Timeout:
    """Build a bounded :class:`httpx.Timeout` from an optional total read cap."""
    if timeout is None:
        return httpx.Timeout(
            DEFAULT_TIMEOUT_SECONDS,
            connect=DEFAULT_CONNECT_TIMEOUT_SECONDS,
            pool=DEFAULT_CONNECT_TIMEOUT_SECONDS,
        )
    seconds = min(max(float(timeout), 0.001), MAX_TIMEOUT_SECONDS)
    return httpx.Timeout(
        seconds,
        connect=min(seconds, DEFAULT_CONNECT_TIMEOUT_SECONDS),
        pool=min(seconds, DEFAULT_CONNECT_TIMEOUT_SECONDS),
    )


@dataclass(frozen=True)
class _RequestPlan:
    method: str
    path: str
    headers: Mapping[str, str] = field(default_factory=dict)
    content: bytes | None = None


def _request_plan(
    method: str, path: str, headers: Mapping[str, str] | None, json_body: Any
) -> _RequestPlan:
    """Encode once before HTTP/retries, preserving exact public SDK numbers."""
    request_headers = dict(headers or {})
    content = None
    if json_body is not None:
        content = stringify_json(json_body).encode("utf-8")
        if not any(name.lower() == "content-type" for name in request_headers):
            request_headers["Content-Type"] = "application/json"
    return _RequestPlan(method, path, request_headers, content)


def _raise_for_status(response: TransportResponse) -> None:
    if response.status_code < 400:
        return
    payload: Any = None
    if response.content:
        try:
            payload = parse_json(response.content)
        except ValueError:
            payload = None
    raise error_from_payload(response.status_code, payload)


class SyncTransport:
    """Blocking transport over :class:`httpx.Client`."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float | None = None,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout_for(timeout),
            follow_redirects=False,
        )
        self._retry = retry if retry is not None else RetryPolicy()
        self._sleep = sleep

    @property
    def timeout(self) -> httpx.Timeout:
        return self._client.timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
    ) -> TransportResponse:
        plan = _request_plan(method, path, headers, json_body)
        last_transport_error: Exception | None = None
        for attempt in range(self._retry.max_retries + 1):
            try:
                raw = self._client.request(
                    plan.method,
                    plan.path,
                    headers=dict(plan.headers),
                    content=plan.content,
                )
            except httpx.TransportError as error:
                last_transport_error = error
                if should_retry(plan.method, None, attempt, self._retry):
                    self._sleep(self._retry.backoff_seconds[attempt])
                    continue
                raise StarIntelConnectionError(
                    f"transport error calling {plan.method} {plan.path}: {error}"
                ) from error
            if should_retry(plan.method, raw.status_code, attempt, self._retry):
                self._sleep(self._retry.backoff_seconds[attempt])
                continue
            response = TransportResponse(
                status_code=raw.status_code, headers=raw.headers, content=raw.content
            )
            _raise_for_status(response)
            return response
        raise StarIntelConnectionError(
            f"transport error calling {plan.method} {plan.path}: {last_transport_error}"
        )

    def close(self) -> None:
        self._client.close()


class AsyncTransport:
    """Async transport over :class:`httpx.AsyncClient`."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float | None = None,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], Any] | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_for(timeout),
            follow_redirects=False,
        )
        self._retry = retry if retry is not None else RetryPolicy()
        self._sleep: Callable[[float], Any] = (
            sleep if sleep is not None else _default_async_sleep
        )

    @property
    def timeout(self) -> httpx.Timeout:
        return self._client.timeout

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
    ) -> TransportResponse:
        plan = _request_plan(method, path, headers, json_body)
        last_transport_error: Exception | None = None
        for attempt in range(self._retry.max_retries + 1):
            try:
                raw = await self._client.request(
                    plan.method,
                    plan.path,
                    headers=dict(plan.headers),
                    content=plan.content,
                )
            except httpx.TransportError as error:
                last_transport_error = error
                if should_retry(plan.method, None, attempt, self._retry):
                    await self._sleep(self._retry.backoff_seconds[attempt])
                    continue
                raise StarIntelConnectionError(
                    f"transport error calling {plan.method} {plan.path}: {error}"
                ) from error
            if should_retry(plan.method, raw.status_code, attempt, self._retry):
                await self._sleep(self._retry.backoff_seconds[attempt])
                continue
            response = TransportResponse(
                status_code=raw.status_code, headers=raw.headers, content=raw.content
            )
            _raise_for_status(response)
            return response
        raise StarIntelConnectionError(
            f"transport error calling {plan.method} {plan.path}: {last_transport_error}"
        )

    async def aclose(self) -> None:
        await self._client.aclose()


async def _default_async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def parse_json_content(content: bytes) -> Any:
    """Parse a response body; empty bodies become ``None``, invalid JSON stays raw."""
    if not content:
        return None
    try:
        return parse_json(content)
    except ValueError:
        return content.decode(errors="replace")
