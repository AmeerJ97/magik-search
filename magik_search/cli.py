from __future__ import annotations

import argparse
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
from .output import (
    print_doctor,
    print_scan_complete,
    print_scan_start,
    print_stats,
    print_topology,
    print_warnings,
    print_welcome,
)
from .scanner import Scanner
from .terminal import wordmark
from .topology import discover_topology
from .tui import Dashboard


class CliError(Exception):
    """Expected operator error with a stable exit status."""


class BrandedArgumentParser(argparse.ArgumentParser):
    def print_help(self, file=None) -> None:
        stream = file or sys.stdout
        logo = wordmark(stream)
        if logo:
            print(logo, file=stream)
            print(file=stream)
        super().print_help(stream)


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
    parser = BrandedArgumentParser(
        prog="magik-search",
        description="Discover files quickly without making physical drives fight each other.",
        epilog=(
            "Quick start:\n"
            "  magik-search doctor\n"
            "  magik-search topology\n"
            "  magik-search scan /data -g '*.xml'\n\n"
            "Run 'magik-search COMMAND --help' for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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

    stats = subparsers.add_parser(
        "stats",
        help="render statistics from a completed run",
        description="Render a summary file, run directory, or the newest run under ./magik-runs.",
    )
    stats.add_argument("summary", nargs="?", type=Path, metavar="SUMMARY_OR_RUN_DIR")
    stats.add_argument("--json", action="store_true", help="re-emit validated JSON")

    subparsers.add_parser("doctor", help="check runtime commands and optional features")
    return parser


def _run_paths(args: argparse.Namespace, run_id: str) -> tuple[Path, Path, Path, Path]:
    output_dir = (args.output_dir or Path("magik-runs") / run_id).expanduser().resolve()
    event_log = (args.event_log or output_dir / "events.jsonl").expanduser().resolve()
    results = (args.results or output_dir / "results.jsonl").expanduser().resolve()
    summary = (args.summary or output_dir / "summary.json").expanduser().resolve()
    return output_dir, event_log, results, summary


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


def _resolve_summary(path: Path | None) -> tuple[Path, dict[str, Any]]:
    if path is not None:
        resolved = path.expanduser()
        if resolved.is_dir():
            resolved = resolved / "summary.json"
        return resolved, _load_summary(resolved)

    candidates = sorted(
        Path("magik-runs").glob("*/summary.json"),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        try:
            return candidate, _load_summary(candidate)
        except CliError:
            continue
    raise CliError("no completed runs found under ./magik-runs; pass a summary file or run directory")


def _doctor() -> int:
    topology = discover_topology()
    rows: list[tuple[str, str, str]] = []
    failures = 0
    for command, required in (("lsblk", True), ("findmnt", True), ("pvs", False), ("lvs", False)):
        path = shutil.which(command)
        warning = next((item for item in topology.warnings if item.startswith(f"{command} ")), None)
        if path is None or warning:
            state = "error" if required else "warning"
            detail = warning or f"not found; {'required' if required else 'optional'}"
            failures += int(required)
        else:
            state = "ok"
            detail = path
        rows.append((command, state, detail))

    classifier = Classifier()
    if classifier.backend == "magika":
        rows.append(("magika", "ok", "content verification enabled"))
    else:
        rows.append(
            (
                "magika",
                "warning",
                f"{classifier.unavailable_reason}; reinstall with ./scripts/install.sh",
            )
        )
    print_doctor(__version__, sys.version.split()[0], sys.platform, rows, failures)
    return 1 if failures else 0


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
    patterns = args.name_glob or ["*fsm*.xml"]
    classifier = Classifier(enabled=not args.no_magika)
    print_scan_start(roots, patterns, classifier.backend, classifier.unavailable_reason)
    print_warnings(topology.warnings)
    try:
        scanner = Scanner(
            topology,
            roots,
            patterns,
            events,
            classifier,
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

    print_scan_complete(
        outcome,
        scanner.interrupted,
        event_log,
        results_path,
        summary_path,
        len(scanner.expanded_mount_roots),
    )
    return 130 if scanner.interrupted else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        print_welcome(parser.format_help())
        return 0
    try:
        if args.command == "scan":
            return _scan(args)
        if args.command == "topology":
            data = discover_topology().as_dict()
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                print_topology(data)
            return 0
        if args.command == "stats":
            summary_path, data = _resolve_summary(args.summary)
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                print_stats(data, summary_path)
            return 0
        if args.command == "doctor":
            return _doctor()
    except CliError as exc:
        print(f"magik-search: error: {exc}", file=sys.stderr)
        return 2
    return 2
