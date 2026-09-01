from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import Mount, PhysicalDrive, Topology


def _command_json(command: list[str], warnings: list[str]) -> dict[str, Any]:
    executable = shutil.which(command[0])
    if not executable:
        warnings.append(f"{command[0]} is unavailable; related topology data omitted")
        return {}
    try:
        result = subprocess.run([executable, *command[1:]], capture_output=True, text=True, check=True, timeout=10)
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        warnings.append(f"{' '.join(command)} failed: {exc}")
        return {}


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def topology_from_reports(
    lsblk_report: dict[str, Any],
    findmnt_report: dict[str, Any] | None = None,
    pvs_report: dict[str, Any] | None = None,
    lvs_report: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> Topology:
    warnings = warnings if warnings is not None else []
    drives: dict[str, PhysicalDrive] = {}
    mount_drives: dict[str, set[str]] = {}
    mount_sources: dict[str, str] = {}
    mount_fstypes: dict[str, str] = {}

    def walk(node: dict[str, Any], ancestors: tuple[str, ...] = ()) -> None:
        name = str(node.get("name") or node.get("kname") or "unknown")
        node_type = str(node.get("type") or "")
        physical = ancestors
        if node_type == "disk":
            drives[name] = PhysicalDrive(
                name=name,
                path=str(node.get("path") or f"/dev/{name}"),
                rotational=bool(_integer(node.get("rota"))),
                size=_integer(node.get("size")),
                model=str(node.get("model") or "").strip(),
            )
            physical = (name,)
        mountpoints = node.get("mountpoints") or []
        if isinstance(mountpoints, str):
            mountpoints = [mountpoints]
        for target in filter(None, mountpoints):
            target = str(target)
            mount_drives.setdefault(target, set()).update(physical)
            mount_sources[target] = str(node.get("path") or f"/dev/{name}")
            mount_fstypes[target] = str(node.get("fstype") or "")
        for child in node.get("children") or []:
            walk(child, physical)

    for device in lsblk_report.get("blockdevices") or []:
        walk(device)

    def add_findmnt(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            target = str(node.get("target") or "")
            if target:
                mount_sources.setdefault(target, str(node.get("source") or ""))
                mount_fstypes.setdefault(target, str(node.get("fstype") or ""))
            add_findmnt(node.get("children") or [])

    if findmnt_report:
        add_findmnt(findmnt_report.get("filesystems") or [])

    mounts = [
        Mount(
            target=target,
            source=mount_sources.get(target, ""),
            fstype=mount_fstypes.get(target, ""),
            drives=tuple(sorted(names)),
        )
        for target, names in mount_drives.items()
    ]
    mounts.sort(key=lambda mount: mount.target)

    def report_rows(report: dict[str, Any] | None, key: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for section in (report or {}).get("report") or []:
            rows.extend({str(k).strip(): str(v).strip() for k, v in row.items()} for row in section.get(key) or [])
        return rows

    return Topology(
        drives=drives,
        mounts=mounts,
        pvs=report_rows(pvs_report, "pv"),
        lvs=report_rows(lvs_report, "lv"),
        warnings=warnings,
    )


def discover_topology() -> Topology:
    warnings: list[str] = []
    lsblk = _command_json(
        ["lsblk", "--json", "--bytes", "-o", "NAME,KNAME,PATH,TYPE,ROTA,SIZE,MODEL,MOUNTPOINTS,FSTYPE"],
        warnings,
    )
    findmnt = _command_json(["findmnt", "--json", "--real", "-o", "TARGET,SOURCE,FSTYPE"], warnings)
    pvs = _command_json(
        ["pvs", "--reportformat", "json", "--units", "b", "--nosuffix", "-o", "pv_name,vg_name,pv_size,pv_free"],
        warnings,
    )
    lvs = _command_json(
        [
            "lvs",
            "--reportformat",
            "json",
            "--units",
            "b",
            "--nosuffix",
            "-o",
            "lv_path,lv_name,vg_name,lv_size,devices",
        ],
        warnings,
    )
    if not lsblk:
        warnings.append("No lsblk topology was returned")
    return topology_from_reports(lsblk, findmnt, pvs, lvs, warnings)


def synthetic_drive(path: Path) -> PhysicalDrive:
    """Fallback lane when a path is not represented by the host block-device view."""
    device = path.stat().st_dev
    return PhysicalDrive(name=f"fs-{device}", path=str(path), rotational=False, size=0, model="unmapped filesystem")
