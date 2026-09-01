from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import time
import uuid
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from . import __version__
from .classifier import Classifier
from .events import EventStream
from .scanner import Scanner
from .topology import discover_topology
from .tui import Dashboard


class CliError(Exception):
    """Expected operator error with a stable exit status."""


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _temperature(value: str) -> float:
    parsed = float(value)
    if not 20 <= parsed <= 120:
        raise argparse.ArgumentTypeError("must be between 20 and 120°C")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="magik-search",
        description="Discover files quickly without making physical drives fight each other.",
        epilog="Run 'magik-search COMMAND --help' for command-specific options.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    scan = subparsers.add_parser(
        "scan",
        help="search filesystem roots with adaptive per-drive workers",
        description="Search roots while adapting concurrency independently for each physical drive.",
    )
    scan.add_argument("roots", nargs="*", type=Path, default=[Path.cwd()], metavar="ROOT")
    scan.add_argument(
        "-g",
        "--name-glob",
        action="append",
        default=[],
        metavar="GLOB",
        help="case-insensitive filename glob (repeatable; default: *fsm*.xml)",
    )
    scan.add_argument(
        "--ssd-workers", type=_positive_int, default=4, metavar="N", help="maximum scouts per SSD/NVMe (default: 4)"
    )
    scan.add_argument(
        "--hdd-workers",
        type=_positive_int,
        default=1,
        metavar="N",
        help="maximum scouts per rotational drive (default: 1)",
    )
    scan.add_argument(
        "--batch-size",
        type=_positive_int,
        default=64,
        metavar="N",
        help="candidate paths per classifier invocation (default: 64)",
    )
    scan.add_argument(
        "--temp-limit",
        type=_temperature,
        default=80.0,
        metavar="°C",
        help="pause dispatch at this CPU temperature (default: 80)",
    )
    scan.add_argument(
        "--cross-filesystems",
        action="store_true",
        help="also cross device boundaries not represented by discovered mount topology",
    )
    scan.add_argument("--no-magika", action="store_true", help="metadata-only mode; never read candidate contents")
    scan.add_argument("--no-tui", action="store_true", help="disable the live dashboard")
    scan.add_argument(
        "--output-dir", type=Path, metavar="DIR", help="run artifact directory (default: ./magik-runs/<run-id>)"
    )
    scan.add_argument("--event-log", type=Path, metavar="FILE", help="override the JSONL event output path")
    scan.add_argument("--results", type=Path, metavar="FILE", help="override the JSONL candidate results path")
    scan.add_argument("--summary", type=Path, metavar="FILE", help="override the JSON summary output path")

    topology = subparsers.add_parser("topology", help="inspect drives, mounts, LVM PVs and LVs")
    topology.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    stats = subparsers.add_parser("stats", help="render statistics from a completed run")
    stats.add_argument("summary", type=Path, metavar="SUMMARY_JSON")
    stats.add_argument("--json", action="store_true", help="re-emit validated JSON")

    subparsers.add_parser("doctor", help="check runtime commands and optional features")
    return parser


def _run_paths(args: argparse.Namespace, run_id: str) -> tuple[Path, Path, Path, Path]:
    output_dir = (args.output_dir or Path("magik-runs") / run_id).expanduser().resolve()
    event_log = (args.event_log or output_dir / "events.jsonl").expanduser().resolve()
    results = (args.results or output_dir / "results.jsonl").expanduser().resolve()
    summary = (args.summary or output_dir / "summary.json").expanduser().resolve()
    return output_dir, event_log, results, summary


def _print_topology(data: dict[str, Any]) -> None:
    print("Physical drives")
    if not data["drives"]:
        print("  none discovered")
    for drive in data["drives"].values():
        media = "HDD" if drive["rotational"] else "SSD/NVMe"
        size = f"{drive['size'] / (1024**3):.1f} GiB" if drive["size"] else "unknown"
        print(f"  {drive['name']:<12} {media:<8} {size:>12}  {drive['model']}")
    print("\nMount → physical drive")
    for mount in data["mounts"]:
        print(f"  {mount['target']:<32} {mount['source']:<28} {','.join(mount['drives']) or '?'}")
    for title, key in (("LVM physical volumes", "pvs"), ("LVM logical volumes", "lvs")):
        if data[key]:
            print(f"\n{title}")
            for row in data[key]:
                print("  " + "  ".join(f"{name}={value}" for name, value in row.items()))
    for warning in data["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)


def _load_summary(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except OSError as exc:
        raise CliError(f"cannot read summary {path}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise CliError(f"invalid summary JSON {path}: line {exc.lineno}, column {exc.colno}") from exc
    required = {"duration", "results", "verified_matches", "workers", "magika_invocations", "lanes"}
    missing = required - data.keys() if isinstance(data, dict) else required
    if missing:
        raise CliError(f"not a magik-search summary; missing: {', '.join(sorted(missing))}")
    return data


def _print_stats(data: dict[str, Any]) -> None:
    workers = data["workers"]
    classifiers = data["magika_invocations"]
    state = "interrupted" if data.get("interrupted") else "complete"
    print(f"Run {state} in {data['duration']:.2f}s")
    print(f"  candidates       {data['results']:,}")
    print(f"  verified matches {data['verified_matches']:,}")
    print(f"  metadata events  {data.get('events', 0):,}")
    print(
        f"  scouts           {workers['spawned']:,}  "
        f"coverage {workers['coverage']:,}  useful {workers['usefulness']:.2%}"
    )
    print(
        f"  classifier runs  {classifiers['spawned']:,}  "
        f"coverage {classifiers['coverage']:,}  useful {classifiers['usefulness']:.2%}"
    )
    if data["lanes"]:
        print("\nDrive lanes")
        for lane in data["lanes"]:
            print(
                f"  {lane['drive']['name']:<12} {lane['entries']:>10,} entries  "
                f"{lane['candidates']:>8,} candidates  {lane['spawned_workers']:>3} scouts  "
                f"{lane['errors']} errors"
            )


def _doctor() -> int:
    rows = []
    failures = 0
    for command, required in (("lsblk", True), ("findmnt", True), ("pvs", False), ("lvs", False)):
        path = shutil.which(command)
        okay = path is not None
        failures += int(required and not okay)
        rows.append((command, "ok" if okay else "missing", path or ("required" if required else "optional")))
    magika = importlib.util.find_spec("magika") is not None
    rows.append(
        (
            "magika",
            "ok" if magika else "missing",
            "classifier enabled" if magika else "optional; metadata mode available",
        )
    )
    print(f"magik-search {__version__}")
    print(f"Python {sys.version.split()[0]} on {sys.platform}")
    for name, status, detail in rows:
        marker = "✓" if status == "ok" else ("✗" if detail == "required" else "○")
        print(f"  {marker} {name:<9} {status:<7} {detail}")
    if failures:
        print("\nDoctor found missing required commands.", file=sys.stderr)
        return 1
    print("\nReady to scan.")
    return 0


def _scan(args: argparse.Namespace) -> int:
    roots = [root.expanduser().resolve() for root in args.roots]
    for root in roots:
        if not root.is_dir():
            raise CliError(f"scan root is not a directory: {root}")
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    output_dir, event_log, results_path, summary_path = _run_paths(args, run_id)
    for root in roots:
        if output_dir == root or output_dir in root.parents:
            raise CliError(f"output directory cannot contain a scan root: {output_dir}")
    try:
        for path in (event_log.parent, results_path.parent, summary_path.parent):
            path.mkdir(parents=True, exist_ok=True)
        events = EventStream(event_log, run_id)
    except OSError as exc:
        raise CliError(f"cannot create run artifacts: {exc}") from exc
    topology = discover_topology()
    try:
        scanner = Scanner(
            topology,
            roots,
            args.name_glob or ["*fsm*.xml"],
            events,
            Classifier(enabled=not args.no_magika),
            ssd_workers=args.ssd_workers,
            hdd_workers=args.hdd_workers,
            batch_size=args.batch_size,
            cross_filesystems=args.cross_filesystems,
            temp_limit=args.temp_limit,
            excluded_paths=(output_dir, event_log, results_path, summary_path),
        )
    except (OSError, ValueError) as exc:
        events.close()
        raise CliError(str(exc)) from exc

    if scanner.expanded_mount_roots and args.no_tui:
        print(
            f"Drive-aware roots: {len(scanner.requested_roots)} requested + "
            f"{len(scanner.expanded_mount_roots)} nested mounts"
        )

    dashboard = Dashboard(scanner, enabled=not args.no_tui)
    dashboard.start()
    try:
        outcome = scanner.run()
    except BaseException:
        dashboard.close()
        with suppress(OSError):
            events.close()
        raise
    dashboard.close()
    try:
        events.close()
    except OSError as exc:
        raise CliError(str(exc)) from exc
    try:
        with results_path.open("w", encoding="utf-8") as results_file:
            for result in scanner.results:
                results_file.write(json.dumps(result, separators=(",", ":"), ensure_ascii=False) + "\n")
        summary_path.write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot write run results: {exc}") from exc

    print(
        f"Scan {'interrupted' if scanner.interrupted else 'complete'}: "
        f"{outcome['results']:,} candidates, {outcome['verified_matches']:,} verified"
    )
    print(f"  events   {event_log}")
    print(f"  results  {results_path}")
    print(f"  summary  {summary_path}")
    if scanner.expanded_mount_roots:
        print(f"  mounts   {len(scanner.expanded_mount_roots)} nested filesystems scanned in drive-aware lanes")
    return 130 if scanner.interrupted else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "scan":
            return _scan(args)
        if args.command == "topology":
            data = discover_topology().as_dict()
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                _print_topology(data)
            return 0
        if args.command == "stats":
            data = _load_summary(args.summary)
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                _print_stats(data)
            return 0
        if args.command == "doctor":
            return _doctor()
    except CliError as exc:
        print(f"magik-search: error: {exc}", file=sys.stderr)
        return 2
    return 2
