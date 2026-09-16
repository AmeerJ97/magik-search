from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TextIO

from .terminal import Theme, bar, format_percent, human_bytes, terminal_width, wordmark


def print_welcome(help_text: str, stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    logo = wordmark(stream)
    if logo:
        print(logo, file=stream)
        print(file=stream)
    print(help_text.rstrip(), file=stream)


def _shorten(value: object, width: int) -> str:
    text = str(value)
    if len(text) <= width:
        return text
    return text[: max(1, width - 1)] + "…"


def print_topology(data: dict[str, Any], stream: TextIO | None = None, error_stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    error_stream = error_stream or sys.stderr
    theme = Theme(stream)
    width = terminal_width(stream)
    drives = list(data["drives"].values())
    print(theme.heading(f"Physical drives ({len(drives)})"), file=stream)
    if not drives:
        print("  none discovered", file=stream)
    for drive in drives:
        media = "HDD" if drive["rotational"] else "SSD/NVMe"
        size = human_bytes(int(drive["size"])) if drive["size"] else "unknown"
        model_width = max(12, width - 39)
        print(
            f"  {drive['name']:<12} {media:<8} {size:>11}  {_shorten(drive['model'] or 'unknown model', model_width)}",
            file=stream,
        )

    mounts = data["mounts"]
    print(f"\n{theme.heading(f'Mounts ({len(mounts)})')}", file=stream)
    if not mounts:
        print("  none discovered", file=stream)
    target_width = min(34, max(18, width // 3))
    source_width = min(30, max(18, width // 3))
    print(f"  {'TARGET':<{target_width}}  {'SOURCE':<{source_width}}  DRIVE", file=stream)
    for mount in mounts:
        drives_text = ",".join(mount["drives"]) or "unmapped"
        print(
            f"  {_shorten(mount['target'], target_width):<{target_width}}  "
            f"{_shorten(mount['source'], source_width):<{source_width}}  {drives_text}",
            file=stream,
        )

    for title, key in (("LVM physical volumes", "pvs"), ("LVM logical volumes", "lvs")):
        if data[key]:
            print(f"\n{theme.heading(title)}", file=stream)
            for row in data[key]:
                print("  " + "  ".join(f"{name}={value}" for name, value in row.items()), file=stream)
    print_warnings(data["warnings"], error_stream)


def print_warnings(warnings: list[str], stream: TextIO | None = None) -> None:
    stream = stream or sys.stderr
    if not warnings:
        return
    theme = Theme(stream)
    print(f"\n{theme.status('warning')} {len(warnings)} topology warning(s)", file=stream)
    for warning in warnings:
        print(f"  - {warning}", file=stream)


def print_stats(data: dict[str, Any], source: Path | None = None, stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    theme = Theme(stream)
    workers = data["workers"]
    classifiers = data["magika_invocations"]
    interrupted = bool(data.get("interrupted"))
    state = "interrupted" if interrupted else "complete"
    marker = theme.status("warning" if interrupted else "ok")
    print(theme.heading("Run statistics"), file=stream)
    print(f"  {marker} Run {state} in {data['duration']:.2f}s", file=stream)
    if source:
        print(f"  summary          {source}", file=stream)
    print(f"  candidates       {data['results']:,}", file=stream)
    print(f"  verified matches {data['verified_matches']:,}", file=stream)
    print(f"  metadata events  {data.get('events', 0):,}", file=stream)
    print(
        f"  scouts           {workers['spawned']:,} runs  {workers['coverage']:,} observations  "
        f"{format_percent(workers['usefulness'])} useful",
        file=stream,
    )
    print(
        f"  classifier       {classifiers['spawned']:,} runs  {classifiers['coverage']:,} candidates  "
        f"{format_percent(classifiers['usefulness'])} verified",
        file=stream,
    )

    if data["lanes"]:
        lane_heading = f"Drive lanes ({len(data['lanes'])})"
        print(f"\n{theme.heading(lane_heading)}", file=stream)
        for lane in data["lanes"]:
            progress = float(lane.get("approximate_progress", 1.0))
            pressure = float(lane.get("io_pressure", 0.0))
            status = str(lane.get("status", state))
            print(
                f"  {lane['drive']['name']:<12} {bar(progress, stream=stream)} {format_percent(progress):>7}≈  "
                f"{status}",
                file=stream,
            )
            print(
                f"    {lane['entries']:,} entries  {lane['candidates']:,} candidates  "
                f"{lane['spawned_workers']} scouts  {lane['errors']} errors  I/O {format_percent(pressure)}",
                file=stream,
            )


def print_doctor(
    version: str,
    python: str,
    platform: str,
    rows: list[tuple[str, str, str]],
    failures: int,
    stream: TextIO | None = None,
    error_stream: TextIO | None = None,
) -> None:
    stream = stream or sys.stdout
    error_stream = error_stream or sys.stderr
    theme = Theme(stream)
    logo = wordmark(stream)
    if logo:
        print(logo, file=stream)
        print(file=stream)
    print(theme.heading("System check"), file=stream)
    print(f"  magik-search {version}  •  Python {python}  •  {platform}", file=stream)
    for name, status, detail in rows:
        print(f"  {theme.status(status)} {name:<10} {detail}", file=stream)
    if failures:
        print("\nDoctor found missing required capabilities.", file=error_stream)
    else:
        warnings = sum(status == "warning" for _, status, _ in rows)
        if warnings:
            print(f"\n{theme.status('warning')} Ready to scan with {warnings} warning(s).", file=stream)
        else:
            print(f"\n{theme.status('ok')} Ready to scan.", file=stream)


def print_scan_start(
    roots: list[Path],
    patterns: list[str],
    backend: str,
    unavailable_reason: str | None,
    stream: TextIO | None = None,
) -> None:
    stream = stream or sys.stdout
    theme = Theme(stream)
    print(theme.heading("Starting scan"), file=stream)
    print(f"  roots       {', '.join(map(str, roots))}", file=stream)
    print(f"  patterns    {', '.join(patterns)}", file=stream)
    if backend == "magika":
        print(f"  classifier  {theme.status('ok')} Magika content verification", file=stream)
    elif unavailable_reason:
        print(f"  classifier  {theme.status('warning')} metadata only ({unavailable_reason})", file=stream)
        print("              reinstall with: ./scripts/install.sh", file=stream)
    else:
        print(f"  classifier  {theme.status('off')} metadata only (explicit)", file=stream)


def print_scan_complete(
    outcome: dict[str, Any],
    interrupted: bool,
    event_log: Path,
    results_path: Path,
    summary_path: Path,
    expanded_mounts: int,
    stream: TextIO | None = None,
) -> None:
    stream = stream or sys.stdout
    theme = Theme(stream)
    state = "Scan interrupted" if interrupted else "Scan complete"
    status = "warning" if interrupted else "ok"
    print(f"\n{theme.heading(state)}", file=stream)
    print(
        f"  {theme.status(status)} {outcome['results']:,} candidates  •  {outcome['verified_matches']:,} verified",
        file=stream,
    )
    print(f"  events   {event_log}", file=stream)
    print(f"  results  {results_path}", file=stream)
    print(f"  summary  {summary_path}", file=stream)
    if expanded_mounts:
        print(f"  mounts   {expanded_mounts} nested filesystems scanned in drive-aware lanes", file=stream)
