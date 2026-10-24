"""Frozen web search results for scenario cases (`evals run --web snapshot`).

Web search in evals is otherwise a mock that only the injection set uses, so scenario runs never
exercise the web fallback. Live search would make runs irreproducible: results change by the
day, and the query depends on what the agent's NLU wrote. Instead each scenario gets one Tavily
search, made once with a fixed query (brand, appliance type and the situation) on the same
whitelisted domains production uses, and saved here. A run serves those results to whichever
query the agent sends, so both agents, and the runs before and after a change, see the same
pages. The pages are not committed (they are third-party content): `fetch` recreates them.

    uv run python -m homehelper_evals.web_snapshots fetch --suite full --suite no_model
"""

import argparse
import asyncio
import hashlib
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from homehelper.core.config import Settings
from homehelper.knowledge.web import (
    MAX_CONTENT_CHARS,
    MAX_RESULTS,
    TavilySearchClient,
    WebSearchClient,
    Whitelist,
)
from homehelper_evals import REPO_ROOT
from homehelper_evals.cases import EvalCase, WebResult

SNAPSHOTS_DIR = REPO_ROOT / "evals" / "cache" / "web_snapshots"
MAX_QUERY_CHARS = 380  # Tavily's limit is 400


class Snapshot(BaseModel):
    query: str
    domains: list[str]
    fetched_at: str
    results: list[WebResult]


def snapshot_key(case: EvalCase) -> str:
    """No-model replays share the snapshot of the case they replay."""
    return case.paired_with or case.id


def needs_snapshot(case: EvalCase) -> bool:
    return case.kind == "scenario" and not case.web_results


def snapshot_query(case: EvalCase) -> str:
    category = case.category.value.replace("_", " ") if case.category else ""
    text = " ".join(p for p in (case.brand, category, case.scenario) if p)
    return text[:MAX_QUERY_CHARS]


def snapshot_path(directory: Path, key: str) -> Path:
    return directory / f"{key}.json"


def _current(directory: Path, case: EvalCase) -> Snapshot | None:
    """The case's snapshot, unless it was searched for other words (the scenario or the
    manifest's brand changed since): a stale snapshot counts as missing."""
    path = snapshot_path(directory, snapshot_key(case))
    if not path.exists():
        return None
    snapshot = Snapshot.model_validate_json(path.read_bytes())
    return snapshot if snapshot.query == snapshot_query(case) else None


def pending(
    cases: Iterable[EvalCase], directory: Path = SNAPSHOTS_DIR, *, force: bool = False
) -> tuple[dict[str, EvalCase], int]:
    """The cases still to search, by snapshot key, and how many already have a snapshot."""
    todo: dict[str, EvalCase] = {}
    kept: set[str] = set()
    for case in cases:
        key = snapshot_key(case)
        if not needs_snapshot(case) or key in todo or key in kept:
            continue
        if _current(directory, case) and not force:
            kept.add(key)
        else:
            todo[key] = case
    return todo, len(kept)


async def search(
    todo: dict[str, EvalCase],
    client: WebSearchClient,
    whitelist: Whitelist,
    *,
    concurrency: int = 4,
    on_done: Callable[[str, Snapshot], None] | None = None,
) -> dict[str, Snapshot]:
    """One search per case, on the domains production would search for its brand. Each one is
    passed to `on_done` as soon as it arrives, so a failed search loses only itself."""
    semaphore = asyncio.Semaphore(concurrency)

    async def one(key: str, case: EvalCase) -> Snapshot | None:
        query = snapshot_query(case)
        domains = whitelist.domains_for(case.brand)
        try:
            async with semaphore:
                hits = await client.search(query, domains, MAX_RESULTS)
        except Exception as exc:  # one bad search must not lose the others
            print(f"search failed for {key}: {exc!r}", file=sys.stderr)
            return None
        snapshot = Snapshot(
            query=query,
            domains=domains,
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
            results=[
                WebResult(url=h.url, title=h.title, content=h.content[:MAX_CONTENT_CHARS])
                for h in hits
                if whitelist.allows(h.url)
            ],
        )
        if on_done is not None:
            on_done(key, snapshot)
        return snapshot

    snapshots = await asyncio.gather(*(one(key, case) for key, case in todo.items()))
    return {key: s for key, s in zip(todo, snapshots, strict=True) if s is not None}


def save(key: str, snapshot: Snapshot, directory: Path = SNAPSHOTS_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    snapshot_path(directory, key).write_text(snapshot.model_dump_json(indent=1) + "\n")


def apply(
    cases: list[EvalCase], directory: Path = SNAPSHOTS_DIR
) -> tuple[list[EvalCase], list[str], str]:
    """The cases with their snapshot's results as `web_results`, the keys with no snapshot, and
    a digest of the snapshots used (for the report)."""
    applied, missing = [], []
    digest = hashlib.sha256()
    for case in cases:
        if not needs_snapshot(case):
            applied.append(case)
            continue
        key = snapshot_key(case)
        snapshot = _current(directory, case)
        if snapshot is None:
            missing.append(key)
            applied.append(case)
            continue
        digest.update(
            key.encode()
            + b"\0"
            + hashlib.sha256(snapshot_path(directory, key).read_bytes()).digest()
        )
        applied.append(case.model_copy(update={"web_results": snapshot.results}))
    return applied, sorted(set(missing)), digest.hexdigest()[:16]


def _cases(suites: list[str], seed: str) -> list[EvalCase]:
    from homehelper_evals.runner import SUITES, build_cases

    return [case for suite in suites for case in build_cases(SUITES[suite], seed=seed)]  # type: ignore[index]


def _fetch(args: argparse.Namespace) -> int:
    settings = Settings()
    key = settings.tavily_api_key.get_secret_value()
    if not key:
        print("TAVILY_API_KEY is not set", file=sys.stderr)
        return 2
    whitelist = Whitelist.load(settings.web_whitelist_path)
    todo, kept = pending(_cases(args.suites, args.seed), args.dir, force=args.force)
    snapshots = asyncio.run(
        search(
            todo,
            TavilySearchClient(key),
            whitelist,
            on_done=lambda k, snapshot: save(k, snapshot, args.dir),
        )
    )
    empty = sum(1 for s in snapshots.values() if not s.results)
    failed = len(todo) - len(snapshots)
    print(
        f"fetched {len(snapshots)} ({empty} with no results, {failed} failed), kept {kept} "
        f"({args.dir})"
    )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_cmd = commands.add_parser("fetch", help="search once per scenario case and save it")
    fetch_cmd.add_argument("--suite", action="append", dest="suites", required=True)
    fetch_cmd.add_argument("--seed", default="v1")
    fetch_cmd.add_argument("--dir", type=Path, default=SNAPSHOTS_DIR)
    fetch_cmd.add_argument("--force", action="store_true", help="search again for every case")
    args = parser.parse_args(argv)
    return _fetch(args)


if __name__ == "__main__":
    raise SystemExit(main())
