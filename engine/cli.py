"""adengine: run AdForge manifests without Claude attached."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from engine.config import ConfigError
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
    project = _project(args)
    project.revise(args.node_id, json.loads(args.json))
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
    rb = add("rollback", cmd_rollback, "restore an earlier version of a node")
    rb.add_argument("node_id")
    rb.add_argument("version", type=int)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.fn(args)
    except (ManifestError, ConfigError, ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
