"""Hermetic tests for the thin transport primitives (timeouts, retry)."""

from __future__ import annotations

import socket
import time
from typing import Any

import pytest

from starintel_client._errors import StarIntelApiError, StarIntelConnectionError
from starintel_client._transport import (
    AsyncTransport,
    RetryPolicy,
    SyncTransport,
    should_retry,
    timeout_for,
)
from tests.mock_starintel import make_server, stop_server


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture(scope="module")
def server() -> Any:
    httpd, base_url = make_server()
    yield {"server": httpd, "base_url": base_url}
    stop_server(httpd)


@pytest.fixture()
def reset_attempts(server: dict[str, Any]) -> None:
    server["server"].attempt_counts.clear()


# ---- Pure retry decision ----------------------------------------------------


def test_should_retry_get_on_retryable_status() -> None:
    policy = RetryPolicy()
    assert should_retry("GET", 503, 0, policy)
    assert should_retry("GET", 502, 0, policy)
    assert should_retry("GET", 504, 0, policy)


def test_should_retry_stops_after_max_retries() -> None:
    policy = RetryPolicy(max_retries=2)
    assert should_retry("GET", 503, 0, policy)
    assert should_retry("GET", 503, 1, policy)
    assert not should_retry("GET", 503, 2, policy)


def test_should_never_retry_post_or_4xx_or_500() -> None:
    policy = RetryPolicy()
    assert not should_retry("POST", 503, 0, policy)
    assert not should_retry("GET", 404, 0, policy)
    assert not should_retry("GET", 401, 0, policy)
    assert not should_retry("GET", 500, 0, policy)


def test_should_retry_get_on_transport_error() -> None:
    policy = RetryPolicy()
    assert should_retry("GET", None, 0, policy)
    assert not should_retry("POST", None, 0, policy)
    assert not should_retry("GET", None, 2, policy)


# ---- Timeout bounds ---------------------------------------------------------


def test_timeout_for_defaults_are_bounded() -> None:
    timeout = timeout_for(None)
    assert timeout.read == 30.0
    assert timeout.connect == 5.0


def test_timeout_for_clamps_to_maximum() -> None:
    timeout = timeout_for(10_000.0)
    assert timeout.read == 120.0
    assert timeout.connect == 5.0


def test_timeout_for_accepts_small_values() -> None:
    timeout = timeout_for(0.5)
    assert timeout.read == 0.5
    assert timeout.connect == 0.5


# ---- Integration against the mock server -----------------------------------


def test_transport_get_success(server: dict[str, Any]) -> None:
    sleeps: list[float] = []
    transport = SyncTransport(server["base_url"], sleep=sleeps.append)
    response = transport.request("GET", "/_retry/ok", headers={})
    assert response.status_code == 200
    assert b"fine" in response.content
    assert response.headers["x-correlation-id"].startswith("mock-cid-")
    assert sleeps == []
    transport.close()


def test_transport_get_retries_until_success(server: dict[str, Any], reset_attempts: None) -> None:
    sleeps: list[float] = []
    transport = SyncTransport(server["base_url"], sleep=sleeps.append)
    response = transport.request("GET", "/_retry/flaky", headers={})
    assert response.status_code == 200
    assert sleeps == [0.05, 0.2]
    transport.close()


def test_transport_get_exhausts_retries_then_raises(server: dict[str, Any]) -> None:
    transport = SyncTransport(server["base_url"], sleep=lambda _s: None)
    with pytest.raises(StarIntelApiError) as excinfo:
        transport.request("GET", "/_retry/always-503", headers={})
    assert excinfo.value.status_code == 503
    assert excinfo.value.code == "unavailable"
    transport.close()


def test_transport_post_is_never_retried(server: dict[str, Any], reset_attempts: None) -> None:
    transport = SyncTransport(server["base_url"], sleep=lambda _s: None)
    with pytest.raises(StarIntelApiError):
        transport.request("POST", "/_retry/post-503", headers={}, json_body={"x": 1})
    assert server["server"].attempt_counts[("POST", "/_retry/post-503")] == 1
    transport.close()


def test_transport_4xx_is_never_retried(server: dict[str, Any]) -> None:
    transport = SyncTransport(server["base_url"], sleep=lambda _s: None)
    with pytest.raises(StarIntelApiError) as excinfo:
        transport.request("GET", "/_missing", headers={})
    assert excinfo.value.status_code == 404
    transport.close()


def test_transport_connection_error_retries_get_then_raises() -> None:
    base_url = f"http://127.0.0.1:{_free_port()}"
    attempts: list[int] = []
    transport = SyncTransport(base_url, sleep=lambda _s: attempts.append(1))
    with pytest.raises(StarIntelConnectionError):
        transport.request("GET", "/health", headers={})
    assert len(attempts) == 2
    transport.close()


def test_transport_connection_error_post_raises_immediately() -> None:
    base_url = f"http://127.0.0.1:{_free_port()}"
    attempts: list[int] = []
    transport = SyncTransport(base_url, sleep=lambda _s: attempts.append(1))
    with pytest.raises(StarIntelConnectionError):
        transport.request("POST", "/auth/login", headers={}, json_body={})
    assert attempts == []
    transport.close()


def test_transport_custom_retry_policy(server: dict[str, Any], reset_attempts: None) -> None:
    sleeps: list[float] = []
    policy = RetryPolicy(max_retries=1, backoff_seconds=(0.0,))
    transport = SyncTransport(server["base_url"], retry=policy, sleep=sleeps.append)
    with pytest.raises(StarIntelApiError):
        transport.request("GET", "/_retry/always-503", headers={})
    assert server["server"].attempt_counts[("GET", "/_retry/always-503")] >= 2
    transport.close()


def test_transport_204_has_empty_content(server: dict[str, Any]) -> None:
    transport = SyncTransport(server["base_url"])
    response = transport.request("GET", "/no-content", headers={})
    assert response.status_code == 204
    assert response.content == b""
    transport.close()


@pytest.mark.asyncio
async def test_async_transport_retries_and_parses(
    server: dict[str, Any], reset_attempts: None
) -> None:
    sleeps: list[float] = []

    async def asleep(seconds: float) -> None:
        sleeps.append(seconds)

    transport = AsyncTransport(server["base_url"], sleep=asleep)
    response = await transport.request("GET", "/_retry/flaky", headers={})
    assert response.status_code == 200
    assert sleeps == [0.05, 0.2]
    await transport.aclose()


@pytest.mark.asyncio
async def test_async_transport_connection_error_retries_then_raises() -> None:
    base_url = f"http://127.0.0.1:{_free_port()}"

    async def asleep(_seconds: float) -> None:
        return None

    transport = AsyncTransport(base_url, sleep=asleep)
    with pytest.raises(StarIntelConnectionError):
        await transport.request("GET", "/health", headers={})
    await transport.aclose()


def test_real_backoff_sleeps_by_default(server: dict[str, Any], reset_attempts: None) -> None:
    transport = SyncTransport(server["base_url"])
    started = time.monotonic()
    response = transport.request("GET", "/_retry/flaky", headers={})
    elapsed = time.monotonic() - started
    assert response.status_code == 200
    assert elapsed >= 0.2
    transport.close()


def test_policy_defaults_are_conservative() -> None:
    policy = RetryPolicy()
    assert policy.max_retries == 2
    assert not should_retry("GET", 200, 0, policy)
