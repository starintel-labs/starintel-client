"""Shared hermetic fixtures for client tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.mock_starintel import MockStarIntelServer, make_server, stop_server


@pytest.fixture(scope="module")
def mock_server() -> Iterator[MockStarIntelServer]:
    httpd, _base_url = make_server()
    yield httpd
    stop_server(httpd)


@pytest.fixture(scope="module")
def mock_base_url(mock_server: MockStarIntelServer) -> str:
    return f"http://127.0.0.1:{mock_server.server_address[1]}"


@pytest.fixture()
def recorded_requests(mock_server: MockStarIntelServer) -> Iterator[Any]:
    """Expose the requests the mock server has recorded so far."""
    yield mock_server.requests
