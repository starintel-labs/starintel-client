"""Typed model and strict parser for the ``actors.list`` registry document.

The server's actor registry (``starintel-actor-registry-v1``) is the
self-describing actor catalog: every registered actor advertises its semantic
identity, the contracts it accepts/produces, capabilities, runtime status, and
— once the server advertises them (starintel-server#40) — the target options
it accepts as client-side hints. Options are parsed strictly when present and
default to an empty tuple when the server does not advertise any.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "ACTOR_REGISTRY_SCHEMA",
    "ActorContract",
    "ActorDescription",
    "ActorOption",
    "ActorRegistry",
    "parse_actor_registry",
]

ACTOR_REGISTRY_SCHEMA = "starintel-actor-registry-v1"


def _require_str(payload: dict[str, Any], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context}: {key!r} must be a non-empty string")
    return value


def _require_str_list(payload: dict[str, Any], key: str, context: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{context}: {key!r} must be a list of strings")
    return tuple(value)


def _require_object(payload: Any, context: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{context} must be a JSON object")
    return payload


@dataclass(frozen=True)
class ActorOption:
    """One advertised target-option hint: ``KEY=JSON`` accepted by the actor."""

    key: str
    description: str
    required: bool
    schema: Any | None


@dataclass(frozen=True)
class ActorContract:
    """One accepts/produces contract: message/document/target kinds."""

    targets: tuple[str, ...]
    documents: tuple[str, ...]
    messages: tuple[str, ...]


@dataclass(frozen=True)
class ActorDescription:
    """One operator-visible actor from the registry catalog."""

    resource_uri: str
    resource_kind: str
    semantic: tuple[str, str, str]
    accepts: ActorContract
    produces: ActorContract
    capabilities: tuple[str, ...]
    source_package: str
    status: str
    ready: bool
    options: tuple[ActorOption, ...] = ()
    observed_at: str | None = None

    def option(self, key: str) -> ActorOption | None:
        """Look up one advertised option hint by key."""
        return next((option for option in self.options if option.key == key), None)


@dataclass(frozen=True)
class ActorRegistry:
    """Parsed ``actors.list`` envelope: the validated actor catalog."""

    schema: str
    actors: tuple[ActorDescription, ...]
    count: int


def _parse_contract(payload: Any, context: str) -> ActorContract:
    contract = _require_object(payload, context)
    return ActorContract(
        targets=_require_str_list(contract, "targets", context),
        documents=_require_str_list(contract, "documents", context),
        messages=_require_str_list(contract, "messages", context),
    )


def _parse_option(payload: Any, context: str) -> ActorOption:
    option = _require_object(payload, context)
    required = option.get("required")
    if not isinstance(required, bool):
        raise ValueError(f"{context}: 'required' must be a boolean")
    schema = option.get("schema")
    if schema is not None and not isinstance(schema, (dict, str, bool, int, float, list)):
        raise ValueError(f"{context}: 'schema' must be a JSON value or null")
    return ActorOption(
        key=_require_str(option, "key", context),
        description=_require_str(option, "description", context),
        required=required,
        schema=schema,
    )


def _parse_semantic(payload: Any, context: str) -> tuple[str, str, str]:
    semantic = _require_object(payload, context)
    return (
        _require_str(semantic, "name", context),
        _require_str(semantic, "version", context),
        _require_str(semantic, "digest", context),
    )


def _parse_actor(payload: Any, index: int) -> ActorDescription:
    context = f"actors[{index}]"
    actor = _require_object(payload, context)
    ready = actor.get("ready")
    if not isinstance(ready, bool):
        raise ValueError(f"{context}: 'ready' must be a boolean")
    provenance = _require_object(actor.get("provenance"), f"{context}.provenance")
    observed_at = actor.get("observedAt")
    if observed_at is not None and not isinstance(observed_at, str):
        raise ValueError(f"{context}: 'observedAt' must be a string or null")
    raw_options = actor.get("options")
    if raw_options is None:
        options: tuple[ActorOption, ...] = ()
    elif isinstance(raw_options, list):
        options = tuple(
            _parse_option(entry, f"{context}.options[{i}]")
            for i, entry in enumerate(raw_options)
        )
        keys = [option.key for option in options]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{context}: duplicate option keys")
    else:
        raise ValueError(f"{context}: 'options' must be a list or null")
    return ActorDescription(
        resource_uri=_require_str(actor, "resourceUri", context),
        resource_kind=_require_str(actor, "resourceKind", context),
        semantic=_parse_semantic(actor.get("semantic"), f"{context}.semantic"),
        accepts=_parse_contract(actor.get("accepts"), f"{context}.accepts"),
        produces=_parse_contract(actor.get("produces"), f"{context}.produces"),
        capabilities=_require_str_list(actor, "capabilities", context),
        source_package=_require_str(
            provenance, "sourcePackage", f"{context}.provenance"
        ),
        status=_require_str(actor, "status", context),
        ready=ready,
        options=options,
        observed_at=observed_at,
    )


def parse_actor_registry(payload: Any) -> ActorRegistry:
    """Parse and validate a ``starintel-actor-registry-v1`` payload.

    Raises :class:`ValueError` for malformed envelopes, schema mismatches, or
    integrity errors (``count`` disagreeing with the actor list).
    """
    if not isinstance(payload, dict):
        raise ValueError("actor registry must be a JSON object")
    if payload.get("status") != "ok":
        raise ValueError("actor registry envelope status must be 'ok'")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("actor registry 'data' must be a JSON object")
    schema = data.get("schema")
    if schema != ACTOR_REGISTRY_SCHEMA:
        raise ValueError(
            f"unsupported actor registry schema {schema!r}, expected {ACTOR_REGISTRY_SCHEMA!r}"
        )
    raw_actors = data.get("actors")
    if not isinstance(raw_actors, list):
        raise ValueError("actor registry 'actors' must be a list")
    count = data.get("count")
    if not isinstance(count, int) or isinstance(count, bool):
        raise ValueError("actor registry 'count' must be an integer")
    actors = tuple(_parse_actor(entry, index) for index, entry in enumerate(raw_actors))
    if count != len(actors):
        raise ValueError("actor registry 'count' disagrees with the actor list")
    return ActorRegistry(schema=ACTOR_REGISTRY_SCHEMA, actors=actors, count=count)
