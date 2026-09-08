# AGENTS.md — starintel-client

Reusable StarIntel Python API client. Forgejo (`git.starintel.actor`, `origin`)
is authoritative.

## Hard rules

1. **Contract-registry routes only.** Discovery from `GET /client-manifest.json`
   and `GET /openapi.json` drives every operation. Legacy server routes are
   forbidden in code, tests, and docs. If the registry lacks an operation, that
   capability is blocked: reference the starintel-server registry-migration
   issue; never hard-code the legacy path.
2. Auth is `Authorization: Bearer <api-key>`; propagate `X-Correlation-ID`;
   normalize server error envelopes (`status`, `msg`, `correlation_id`, `code`).
3. Effects (HTTP) behind thin transport primitives; deterministic logic
   (discovery parsing, envelope mapping, correlation ids) stays testable.
4. Stop on blockers: record in a forgejo issue with evidence, implement the
   unblocked remainder (ports + fakes), stop.

## Process

- Work in git worktrees on branches `rage/<issue>-<slug>` (git-worktrees skill).
- **Auto-RAGE** is the selected control plane (operator decision, 2026-09-08):
  run Analyze → Design → Adversarial review → Decision → Realize and record the
  decision in the run log created by the rage skill's
  `scripts/init-run.py <issue> <slug> --repo <checkout>`. No human gates.
- TDD: smallest deterministic test first; red → implement → green.
- Gates at the exact candidate HEAD: `pytest`, `ruff check .`, `mypy`
  (strict). Record via `prolog-verify observe` after
  `prolog-verify init --task <short-id>` in the worktree (`.prolog/` local).
- Hermetic tests by default; live server tests opt-in via `STARINTEL_LIVE_TEST`.
- Commits: concise imperative subject; never force-push shared branches.
