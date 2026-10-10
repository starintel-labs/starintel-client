"""The real sync/async HTTP boundary uses the public canonical JSON codec."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

import httpx
import pytest
from starintel_canonical import RawJsonNumber, parse_json, stringify_json

from starintel_client._errors import StarIntelApiError
from starintel_client._transport import AsyncTransport, SyncTransport, parse_json_content

EXACT = "0.12345678901234567890123456789"
HUGE = "1e999999999999999999999999999999999999"


def _stub_http(
    monkeypatch: pytest.MonkeyPatch, status: int, content: bytes, requests: list[httpx.Request]
) -> None:
    def send(_self: httpx.Client, request: httpx.Request, **_kwargs: Any) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=content, request=request)

    async def asend(
        _self: httpx.AsyncClient, request: httpx.Request, **_kwargs: Any
    ) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=content, request=request)

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(httpx.AsyncClient, "send", asend)


async def _request(asynchronous: bool, *, method: str = "POST", **kwargs: Any) -> Any:
    if asynchronous:
        transport = AsyncTransport("https://fixture.example")
        try:
            return await transport.request(method, "/operation", **kwargs)
        finally:
            await transport.aclose()
    transport_sync = SyncTransport("https://fixture.example")
    try:
        return transport_sync.request(method, "/operation", **kwargs)
    finally:
        transport_sync.close()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_exact_request_and_response(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    requests: list[httpx.Request] = []
    payload = {
        "extensions": {"fraction": Decimal(EXACT), "huge": RawJsonNumber(HUGE)},
        "items": [True, None, 2**100, "café"],
    }
    wire = stringify_json(payload).encode("utf-8")
    _stub_http(monkeypatch, 200, wire, requests)
    with localcontext() as context:
        context.prec = 4
        response = await _request(
            asynchronous, json_body=payload, headers={"X-Correlation-ID": "exact-fixture"}
        )
    assert requests[0].content == wire
    assert requests[0].headers["content-type"] == "application/json"
    assert requests[0].headers["x-correlation-id"] == "exact-fixture"
    assert parse_json_content(response.content) == payload
    assert stringify_json(parse_json_content(response.content)).encode() == wire


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_exact_error_info(monkeypatch: pytest.MonkeyPatch, asynchronous: bool) -> None:
    requests: list[httpx.Request] = []
    _stub_http(
        monkeypatch,
        422,
        ('{"msg":"invalid","code":"invalid","info":{"amount":' + EXACT + "}}").encode(),
        requests,
    )
    with pytest.raises(StarIntelApiError) as error:
        await _request(asynchronous, json_body={})
    assert error.value.info["amount"] == Decimal(EXACT)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("body", [None, {}, [], False, 0])
@pytest.mark.asyncio
async def test_body_presence_and_headers(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool, body: Any
) -> None:
    requests: list[httpx.Request] = []
    _stub_http(monkeypatch, 204, b"", requests)
    await _request(
        asynchronous, json_body=body, headers={"CONTENT-TYPE": "application/vnd.starintel+json"}
    )
    assert requests[0].content == (b"" if body is None else stringify_json(body).encode())
    assert requests[0].headers["content-type"] == "application/vnd.starintel+json"
    assert len(requests[0].headers.get_list("content-type")) == 1


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("invalid", [float("nan"), Decimal("Infinity"), {"nested": object()}])
@pytest.mark.asyncio
async def test_invalid_payload_rejected_before_http(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool, invalid: Any
) -> None:
    requests: list[httpx.Request] = []
    _stub_http(monkeypatch, 200, b"{}", requests)
    with pytest.raises((ValueError, TypeError)):
        await _request(asynchronous, json_body=invalid)
    assert requests == []


def test_exact_parse_and_compatibility_fallbacks() -> None:
    assert parse_json_content(EXACT.encode()) == Decimal(EXACT)
    assert parse_json_content(HUGE.encode()) == RawJsonNumber(HUGE)
    assert parse_json_content(b"") is None
    assert parse_json_content(b"null") is None
    assert parse_json_content(b"false") is False
    assert parse_json_content(b"[1,2]") == [1, 2]
    assert parse_json_content(b"not-json") == "not-json"
    assert parse_json_content(b"\xff") == "\ufffd"
    assert parse_json_content(b"NaN") == "NaN"
    assert parse_json(stringify_json({"big": 2**100}))["big"] == 2**100


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_absent_body_does_not_add_content_type(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    requests: list[httpx.Request] = []
    _stub_http(monkeypatch, 204, b"", requests)
    await _request(asynchronous)
    assert requests[0].content == b""
    assert "content-type" not in requests[0].headers


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_retry_reuses_encoded_bytes(
    monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    from starintel_client import _transport

    requests: list[httpx.Request] = []
    payload = {"value": Decimal(EXACT)}
    wire = stringify_json(payload).encode()
    encoded: list[Any] = []

    def encode(value: Any) -> str:
        encoded.append(value)
        return stringify_json(value)

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload["value"] = Decimal("7")
        status = 503 if len(requests) == 1 else 200
        return httpx.Response(status, content=wire, request=request)

    def send(_self: httpx.Client, request: httpx.Request, **_kwargs: Any) -> httpx.Response:
        return respond(request)

    async def asend(
        _self: httpx.AsyncClient, request: httpx.Request, **_kwargs: Any
    ) -> httpx.Response:
        return respond(request)

    monkeypatch.setattr(_transport, "stringify_json", encode)
    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(httpx.AsyncClient, "send", asend)
    response = await _request(asynchronous, method="GET", json_body=payload)
    assert len(encoded) == 1
    assert [request.content for request in requests] == [wire, wire]
    assert parse_json_content(response.content) == {"value": Decimal(EXACT)}
