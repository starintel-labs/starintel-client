"""Actor discovery: typed actors.list parsing and client convenience."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from starintel_client import AsyncStarIntelClient, StarIntelClient, UnknownOperationError
from starintel_client._actors import (
    ActorDescription,
    ActorOption,
    parse_actor_registry,
)
from tests.mock_starintel import API_KEY, MockStarIntelServer, fixture_actor_registry

# -- registry parsing ------------------------------------------------------


def test_parses_full_registry_with_options() -> None:
    registry = parse_actor_registry(fixture_actor_registry())
    assert registry.schema == "starintel-actor-registry-v1"
    assert registry.count == 3
    assert len(registry.actors) == 3

    reddit = registry.actors[0]
    assert reddit.resource_uri == "star://actor/starintel-labs/reddit"
    assert reddit.resource_kind == "actor"
    assert reddit.semantic == ("reddit", "1.2.0", "sha256:abc")
    assert reddit.accepts.targets == (":target",)
    assert reddit.produces.documents == ("reddit:user", "reddit:post")
    assert reddit.capabilities == ("http", "rabbitmq")
    assert reddit.status == "online"
    assert reddit.ready is True
    assert reddit.options == (
        ActorOption(
            key="backend",
            description="arctic-shift or browser",
            required=False,
            schema={"type": "string", "enum": ["arctic-shift", "browser"]},
        ),
        ActorOption(
            key="limit",
            description="max documents per run",
            required=False,
            schema={"type": "integer", "minimum": 1},
        ),
    )
    assert reddit.option("backend") is reddit.options[0]
    assert reddit.option("missing") is None


def test_registry_entry_without_options_yields_empty_hints() -> None:
    registry = parse_actor_registry(fixture_actor_registry())
    watchlist = registry.actors[1]
    assert watchlist.options == ()
    assert watchlist.option("anything") is None
    assert watchlist.ready is False
    assert watchlist.status == "unavailable"
    assert watchlist.observed_at == "2026-11-04T00:00:00Z"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: d.__setitem__("status", "error"), id="not-ok"),
        pytest.param(lambda d: d["data"].__setitem__("schema", "other"), id="schema"),
        pytest.param(lambda d: d["data"].__setitem__("count", 99), id="count"),
        pytest.param(lambda d: d["data"].__setitem__("actors", {}), id="actors-type"),
        pytest.param(
            lambda d: d["data"]["actors"][0].__setitem__("ready", "yes"), id="ready-type"
        ),
        pytest.param(
            lambda d: d["data"]["actors"][0]["options"][0].__setitem__("key", ""),
            id="option-key",
        ),
        pytest.param(
            lambda d: d["data"]["actors"][0]["options"].append(
                {"key": "backend", "description": "dup", "required": False, "schema": None}
            ),
            id="option-duplicate",
        ),
        pytest.param(
            lambda d: d["data"]["actors"][0]["semantic"].pop("digest"), id="semantic"
        ),
    ],
)
def test_malformed_registry_rejected(mutate: Callable[[dict[str, Any]], None]) -> None:
    payload = fixture_actor_registry()
    mutate(payload)
    with pytest.raises(ValueError):
        parse_actor_registry(payload)


def test_non_object_registry_rejected() -> None:
    with pytest.raises(ValueError):
        parse_actor_registry([])


# -- client convenience ----------------------------------------------------


def test_list_actors_through_mock(mock_base_url: str, mock_server: MockStarIntelServer) -> None:
    mock_server.enable_actor_ops()
    try:
        with StarIntelClient(mock_base_url, api_key=API_KEY) as client:
            actors = client.list_actors()
        assert isinstance(actors, list)
        assert all(isinstance(actor, ActorDescription) for actor in actors)
        assert actors[0].options[0].key == "backend"
    finally:
        mock_server.disable_actor_ops()


def test_list_actors_raises_when_not_contracted(mock_base_url: str) -> None:
    with (
        pytest.raises(UnknownOperationError),
        StarIntelClient(mock_base_url) as client,
    ):
        client.list_actors()


@pytest.mark.asyncio
async def test_async_list_actors(mock_base_url: str, mock_server: MockStarIntelServer) -> None:
    mock_server.enable_actor_ops()
    try:
        async with AsyncStarIntelClient(mock_base_url, api_key=API_KEY) as client:
            actors = await client.list_actors()
        assert actors[1].resource_kind == "actor"
    finally:
        mock_server.disable_actor_ops()
