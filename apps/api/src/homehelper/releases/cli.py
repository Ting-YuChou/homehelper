"""`homehelper release ...`: draft a release manifest from eval reports and check its gates
(M7-03, spec §17.3). Run from the repo root: report paths are repo-relative."""

from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError

from homehelper.core.config import get_settings
from homehelper.releases.draft import DraftError, draft_manifest
from homehelper.releases.gates import check_gates, format_table, load_reports, read_report
from homehelper.releases.manifest import dump_manifest, manifest_path, read_manifest

app = typer.Typer(no_args_is_help=True, help="Release manifests and gates (M7).")


def _pairs(values: list[str], option: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for value in values:
        key, sep, rest = value.partition("=")
        if not sep or not key or not rest:
            raise typer.BadParameter(f"expected NAME=VALUE, got {value!r}", param_hint=option)
        if key in pairs:
            raise typer.BadParameter(f"{key!r} given twice", param_hint=option)
        pairs[key] = rest
    return pairs


@app.command("check")
def check(
    manifest: Annotated[Path, typer.Argument(help="releases/<id>.yaml")],
) -> None:
    """Check the manifest's gates against its eval reports; exit 1 if any gate fails."""
    try:
        release = read_manifest(manifest)
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        raise typer.BadParameter(str(exc), param_hint="MANIFEST") from exc
    results = check_gates(release, load_reports(release, Path.cwd()))
    typer.echo(f"release {release.id} (git {release.git_sha})")
    typer.echo(format_table(results))
    failed = [r for r in results if not r.passed]
    if failed:
        typer.echo(f"{len(failed)} of {len(results)} gates failed", err=True)
        raise typer.Exit(1)
    typer.echo(f"all {len(results)} gates passed")


@app.command("draft")
def draft(
    release_id: Annotated[str, typer.Option("--id", help="Release id, e.g. r2026.11.01-1")],
    report: Annotated[
        list[str], typer.Option(help="SUITE=PATH of an `evals run --release <id>` report")
    ],
    gate: Annotated[
        list[str] | None,
        typer.Option(help="NAME=VALUE, e.g. resolution_rate_min=0.6 (required gate)"),
    ] = None,
    kb_version: Annotated[str | None, typer.Option(help="kb_YYYYMMDD_NN evaluated")] = None,
    image: Annotated[str | None, typer.Option(help="Evaluated image digest (M8)")] = None,
    releases_dir: Annotated[
        Path | None, typer.Option(help="Where to write <id>.yaml (default: RELEASES_DIR)")
    ] = None,
) -> None:
    """Write releases/<id>.yaml; git_sha and model overrides come from the reports."""
    gates: dict[str, float] = {}
    for name, value in _pairs(gate or [], "--gate").items():
        try:
            gates[name] = float(value)
        except ValueError:
            raise typer.BadParameter(
                f"{name}: {value!r} is not a number", param_hint="--gate"
            ) from None
    reports = {
        suite: (path, read_report(Path(path))) for suite, path in _pairs(report, "--report").items()
    }
    try:
        manifest = draft_manifest(
            release_id, reports, gates=gates, kb_version=kb_version, image=image
        )
    except DraftError as exc:
        typer.echo(f"refusing to draft {release_id}: {exc}", err=True)
        raise typer.Exit(1) from None
    out = manifest_path(releases_dir or get_settings().releases_dir, manifest.id)
    if out.exists():
        typer.echo(f"{out} already exists; releases are immutable", err=True)
        raise typer.Exit(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dump_manifest(manifest))
    typer.echo(str(out))
