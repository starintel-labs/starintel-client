"""Live server tests. Opt-in only: STARINTEL_LIVE_TEST=1.

Skipped entirely in hermetic runs (the default).
"""

from __future__ import annotations

import os

import pytest

from starintel_client import AsyncStarIntelClient, StarIntelClient

pytestmark = pytest.mark.skipif(
    os.environ.get("STARINTEL_LIVE_TEST") != "1",
    reason="live tests are opt-in via STARINTEL_LIVE_TEST=1",
)

BASE_URL = os.environ.get("STARINTEL_BASE_URL", "http://127.0.0.1:5000")


def test_live_discovery_and_health() -> None:
    client = StarIntelClient(base_url=BASE_URL)
    manifest = client.discover()
    assert manifest.schema_name == "starintel-client-manifest-v1"
    assert client.health().status_code == 200
    client.close()


async def test_live_async_discovery() -> None:
    async with AsyncStarIntelClient(base_url=BASE_URL) as client:
        manifest = await client.discover()
        assert manifest.has_operation("health.get")
