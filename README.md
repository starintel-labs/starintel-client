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
