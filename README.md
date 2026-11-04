# starintel-client

Reusable StarIntel Python API client.

**Contract-registry routes only.** The client is driven by the server's
machine-readable contract — `GET /client-manifest.json` and
`GET /openapi.json` — and never hard-codes legacy routes
(`/new/document/:dtype`, `/documents/bulk`, `/document/:id`,
`/new/target/:actor`, `GET /search`, view query routes are forbidden).
Operations the registry does not expose are out of scope until the server
contracts them (see starintel-server registry migration).

See `AGENTS.md` for the binding agent process.

### Actor discovery and option hints

`list_actors()` fetches the server's self-describing actor catalog through the
contracted `actors.list` operation (`GET /v1/actors`, envelope
`starintel-actor-registry-v1`). Every `ActorDescription` advertises its
`resource_uri`, semantic identity, the contracts it `accepts`/`produces`,
`capabilities`, runtime `status`/`ready`, and — when the server provides them
— the target `options` it accepts as `ActorOption` hints (key, description,
required flag, JSON shape). Clients can use these hints to complete or
validate `KEY=JSON` target options before submitting `targets.create`:

```python
from starintel_client import StarIntelClient

with StarIntelClient("https://star.example", api_key=key) as client:
    actors = client.list_actors()
    backend = actors[0].option("backend")  # ActorOption or None
```

`parse_actor_registry()` validates the same envelope deterministically
without HTTP. Option advertisement is optional wire-side: registries without
`options` parse to an empty hint tuple (server-side advertisement is tracked
as starintel-server#40).

### Exact JSON numbers

The shared sync/async transport uses the public `starintel_canonical.parse_json`
and `stringify_json` APIs from the pinned StarIntel SDK. Request bodies may
contain finite `Decimal` and `RawJsonNumber` values; they are sent as JSON numeric
tokens without binary-float conversion. Responses and normalized error `info`
retain exact numbers too. Integers, booleans, nulls and strings retain their usual
JSON meanings. Fractional response values may therefore be `Decimal` (or
`RawJsonNumber` for extreme exponents); use the SDK's `stringify_json` when
re-encoding them rather than the standard JSON encoder.

An absent body remains absent. Explicit content-type headers are preserved;
JSON bodies get `application/json` when no content type is supplied. Invalid or
non-finite request data fails before HTTP. Empty and non-JSON response handling,
authentication, correlation IDs, and conservative retry rules are unchanged.
