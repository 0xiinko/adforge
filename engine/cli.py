"""adengine: run AdForge manifests without Claude attached."""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

from engine.assembly.ffmpeg import REQUIRED_FILTERS, FFmpeg
from engine.config import ConfigError, load_config
from engine.core.graph import ManifestError, load_manifest
from engine.core.project import Project
from engine.core.scheduler import RunReport


def _project(args: argparse.Namespace) -> Project:
    return Project.open(args.project, args.config)


def _print_report(report: RunReport) -> None:
    print(
        f"ran {len(report.ran)}, cached {len(report.skipped)}, failed {len(report.failed)}, "
        f"needs_review {len(report.needs_review)}, blocked {len(report.blocked)}"
    )
    for nid in report.failed + report.needs_review:
        print(f"ATTENTION {nid}")


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        manifest = load_manifest(Path(args.project) / "manifest.json")
    except ManifestError as e:
        for err in e.errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print(f"OK: {len(manifest.nodes)} nodes")
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    report = _project(args).dry_run(args.only)
    for p in report.to_run:
        note = "" if p.provider_available else "  (provider not registered)"
        print(f"RUN    {p.node_id:<28} {p.provider}/{p.model}  ${p.cost_usd:.2f}{note}")
    for nid in report.cached:
        print(f"CACHED {nid}")
    print(f"{len(report.to_run)} to run, {len(report.cached)} cached, estimated cost: ${report.total_cost:.2f}")
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    report = _project(args).dry_run(args.only)
    print(f"estimated cost: ${report.total_cost:.2f} for {len(report.to_run)} nodes")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    report = asyncio.run(_project(args).run(args.only))
    _print_report(report)
    return 0 if report.ok else 1


def cmd_status(args: argparse.Namespace) -> int:
    for nid, st in _project(args).status():
        line = f"{nid:<28} {st.status:<13} v{st.version}"
        if st.pinned_version is not None:
            line += " (pinned)"
        if st.reason:
            line += f"  {st.reason}: {st.message or ''}"
        print(line)
    return 0


def cmd_revise(args: argparse.Namespace) -> int:
    changes = json.loads(args.json)
    if not isinstance(changes, dict):
        print("ERROR: --json must be an object", file=sys.stderr)
        return 1
    project = _project(args)
    project.revise(args.node_id, changes)
    print(f"revised {args.node_id}")
    if args.no_run:
        return 0
    report = asyncio.run(project.run())
    _print_report(report)
    return 0 if report.ok else 1


def cmd_rollback(args: argparse.Namespace) -> int:
    new_version = _project(args).rollback(args.node_id, args.version)
    print(f"{args.node_id} restored from v{args.version} as v{new_version} (pinned until next revise)")
    return 0


async def _doctor_checks(ff: FFmpeg) -> tuple[str | None, list[str]]:
    try:
        return await ff.version(), await ff.missing_filters()
    except Exception:  # binary missing or broken: report every filter as missing
        return None, list(REQUIRED_FILTERS)


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config(args.config).assembly
    ff = FFmpeg(cfg)
    ok = True
    for label, binary in (("ffmpeg", cfg.ffmpeg), ("ffprobe", cfg.ffprobe)):
        found = shutil.which(binary) is not None
        ok &= found
        print(f"{label}: {'found' if found else 'NOT FOUND'} ({binary})")
    version, missing = asyncio.run(_doctor_checks(ff))
    if version:
        print(f"version: {version}")
    for f in REQUIRED_FILTERS:
        print(f"{'MISSING' if f in missing else 'OK':<7} {f}")
    if missing:
        ok = False
        print("hint: on macOS install an ffmpeg build with libass and freetype (e.g. the homebrew-ffmpeg tap)")
    print(f"font: {cfg.font}")
    if cfg.font_file:
        exists = Path(cfg.font_file).exists()
        ok &= exists
        print(f"font_file: {cfg.font_file} ({'exists' if exists else 'NOT FOUND'})")
    else:
        print("font_file: (none; fontconfig family name is used)")
    return 0 if ok else 1


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="adengine", description="AdForge render engine")
    p.add_argument("--config", type=Path, default=None, help="config YAML (default: <project>/config.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn, help_text: str, targets: bool = False) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("project", type=Path)
        if targets:
            sp.add_argument("--only", action="append", default=None, metavar="PATTERN",
                            help="node id glob; repeatable (ancestors are included)")
        sp.set_defaults(fn=fn)
        return sp

    add("validate", cmd_validate, "validate manifest.json")
    add("dry-run", cmd_dry_run, "show what would run and the estimated cost; no API calls", targets=True)
    add("estimate", cmd_estimate, "estimated cost of what would run", targets=True)
    add("run", cmd_run, "render stale nodes", targets=True)
    add("status", cmd_status, "per-node status")
    rv = add("revise", cmd_revise, "change one node, then re-render what it affects")
    rv.add_argument("node_id")
    rv.add_argument("--json", required=True, help='changes, e.g. \'{"prompt": "..."}\'')
    rv.add_argument("--no-run", action="store_true")
    dr = sub.add_parser("doctor", help="check ffmpeg, required filters and fonts")
    dr.add_argument("--config", type=Path, default=argparse.SUPPRESS, help="config YAML (default: built-in)")
    dr.set_defaults(fn=cmd_doctor)
    rb = add("rollback", cmd_rollback, "restore an earlier version of a node")
    rb.add_argument("node_id")
    rb.add_argument("version", type=int)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.fn(args)
    except (ManifestError, ConfigError, ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as e:
        message = e.args[0] if isinstance(e, KeyError) and e.args else e
        print(f"ERROR: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
