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
