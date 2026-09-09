"""Anti-legacy regression: forbidden legacy server routes must never appear
under src/.

The literals live only here (tests/), where they are needed to scan for them.
AGENTS.md hard rule 1: contract-registry routes only.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

FORBIDDEN_ROUTE_LITERALS: tuple[str, ...] = (
    "/new/document/:dtype",
    "/new/document/{dtype}",
    "/documents/bulk",
    "/document/:id",
    "/document/{id}",
    "/new/target/:actor",
    "/new/target/{actor}",
    "/search",
    "/views/:design/:view",
    "/views/{design}/{view}",
)


def find_legacy_routes(root: Path) -> list[tuple[Path, str]]:
    """Return (file, literal) pairs for every forbidden literal under root."""
    hits: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        for literal in FORBIDDEN_ROUTE_LITERALS:
            if literal in text:
                hits.append((path, literal))
    return hits


def test_no_legacy_routes_under_src() -> None:
    src = Path(__file__).resolve().parent.parent / "src"
    hits = find_legacy_routes(src)
    assert hits == [], f"forbidden legacy routes under src/: {hits}"


def test_scanner_detects_planted_legacy_route() -> None:
    """Prove the scanner fires when a forbidden literal is present."""
    with tempfile.TemporaryDirectory() as tmp:
        planted = Path(tmp) / "planted.py"
        planted.write_text('ROUTES = ["' + FORBIDDEN_ROUTE_LITERALS[0] + '"]\n', encoding="utf-8")
        hits = find_legacy_routes(Path(tmp))
        assert (planted, FORBIDDEN_ROUTE_LITERALS[0]) in hits


def test_scanner_ignores_clean_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        clean = Path(tmp) / "clean.py"
        clean.write_text('ROUTES = ["/health", "/auth/users"]\n', encoding="utf-8")
        assert find_legacy_routes(Path(tmp)) == []
