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
from engine.providers.base import ProviderError


def _project(args: argparse.Namespace) -> Project:
    return Project.open(args.project, args.config)


def _print_report(report: RunReport) -> None:
    line = (
        f"ran {len(report.ran)}, cached {len(report.skipped)}, failed {len(report.failed)}, "
        f"needs_review {len(report.needs_review)}, blocked {len(report.blocked)}"
    )
    if report.awaiting:
        line += f", awaiting {len(report.awaiting)}"
    print(line)
    for nid in report.failed + report.needs_review:
        print(f"ATTENTION {nid}")
    for nid in report.awaiting:
        print(f"AWAITING {nid}")


def _exit_code(report: RunReport) -> int:
    """0 done; 1 something failed, needs review or is blocked; 3 only waiting for `adengine supply`."""
    if report.failed or report.needs_review or report.blocked:
        return 1
    return 3 if report.awaiting else 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        manifest = load_manifest(Path(args.project) / "manifest.json")
    except ManifestError as e:
        for err in e.errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    errors = _project(args).external_errors(manifest)
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    if errors:
        return 1
    print(f"OK: {len(manifest.nodes)} nodes")
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    report = _project(args).dry_run(args.only)
    for p in report.to_run:
        if p.external:
            note = "  (external: supplied by Claude)"
        else:
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
    return _exit_code(report)


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
    return _exit_code(report)


def cmd_rollback(args: argparse.Namespace) -> int:
    new_version = _project(args).rollback(args.node_id, args.version)
    print(f"{args.node_id} restored from v{args.version} as v{new_version} (pinned until next revise)")
    return 0


def cmd_external(args: argparse.Namespace) -> int:
    nodes = _project(args).external_nodes()
    if args.json:
        print(json.dumps(nodes, indent=2))
        return 0
    if not nodes:
        print("nothing awaiting external supply")
    for n in nodes:
        print(f"{n['id']:<28} {n['type']:<6} {n['provider']}/{n['model']}")
    return 0


def cmd_supply(args: argparse.Namespace) -> int:
    project = _project(args)
    if args.failed is not None or args.refused is not None:
        if args.file is not None:
            print("ERROR: give a file or --failed/--refused, not both", file=sys.stderr)
            return 1
        refused = args.refused is not None
        project.supply_failure(args.node_id, refused=refused, message=args.refused if refused else args.failed)
        print(f"{args.node_id} marked {'needs_review (refused)' if refused else 'failed'}")
        return 0
    if args.file is None or not args.ref:
        print("ERROR: supply needs a file and --ref (or --failed/--refused)", file=sys.stderr)
        return 1
    version = project.supply(
        args.node_id, args.file, ref=args.ref, external_id=args.external_id, fingerprint=args.fingerprint,
    )
    print(f"supplied {args.node_id} as v{version}")
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
    ex = add("external", cmd_external, "list nodes waiting for an external render (adengine supply)")
    ex.add_argument("--json", action="store_true", help="full details: prompt, inputs, external_inputs, fingerprint")
    sp = add("supply", cmd_supply, "hand in a file rendered outside the engine, or report that it failed")
    sp.add_argument("node_id")
    sp.add_argument("file", nargs="?", type=Path, default=None)
    sp.add_argument("--ref", help="the provider's own path/URL for this result; later external nodes use it as input")
    sp.add_argument("--id", dest="external_id", default=None, help="the provider's generation id")
    sp.add_argument("--fingerprint", default=None, help="from `adengine external`; rejects the file if the node changed")
    bad = sp.add_mutually_exclusive_group()
    bad.add_argument("--failed", metavar="MESSAGE", default=None, help="the external render failed")
    bad.add_argument("--refused", metavar="MESSAGE", default=None, help="the external provider refused the prompt")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.fn(args)
    except (ManifestError, ConfigError, ProviderError, ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as e:
        message = e.args[0] if isinstance(e, KeyError) and e.args else e
        print(f"ERROR: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
