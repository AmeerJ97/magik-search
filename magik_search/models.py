from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PhysicalDrive:
    name: str
    path: str
    rotational: bool
    size: int
    model: str = ""


@dataclass(frozen=True)
class Mount:
    target: str
    source: str
    fstype: str
    drives: tuple[str, ...]


@dataclass
class Topology:
    drives: dict[str, PhysicalDrive]
    mounts: list[Mount]
    pvs: list[dict[str, str]] = field(default_factory=list)
    lvs: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def drives_for(self, path: Path) -> tuple[str, ...]:
        resolved = str(path.resolve())
        matches = [
            mount
            for mount in self.mounts
            if resolved == mount.target or resolved.startswith(mount.target.rstrip("/") + "/")
        ]
        return max(matches, key=lambda mount: len(mount.target)).drives if matches else ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "drives": {name: asdict(drive) for name, drive in self.drives.items()},
            "mounts": [asdict(mount) for mount in self.mounts],
            "pvs": self.pvs,
            "lvs": self.lvs,
            "warnings": self.warnings,
        }


@dataclass
class WorkerStats:
    worker_id: str
    drive: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    directories: int = 0
    entries: int = 0
    candidates: int = 0
    matches: int = 0
    errors: int = 0

    @property
    def duration(self) -> float:
        return (self.ended_at or time.time()) - self.started_at

    @property
    def coverage(self) -> int:
        return self.directories + self.entries

    @property
    def usefulness(self) -> float:
        # For traversal workers, useful coverage is candidate yield. Verified
        # matches belong to the downstream classifier invocation statistics.
        return self.candidates / self.entries if self.entries else 0.0


@dataclass
class ClassifierStats:
    invocation_id: str
    started_at: float
    ended_at: float
    candidates: int
    matches: int
    backend: str
    error: str | None = None


@dataclass
class LaneStats:
    drive: PhysicalDrive
    roots: list[str] = field(default_factory=list)
    max_workers: int = 1
    allowed_workers: int = 1
    active_workers: int = 0
    spawned_workers: int = 0
    discovered_dirs: int = 0
    processed_dirs: int = 0
    entries: int = 0
    candidates: int = 0
    matches: int = 0
    errors: int = 0
    io_pressure: float = 0.0
    status: str = "pending"
    current_paths: dict[str, str] = field(default_factory=dict)
    recent_paths: list[str] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def approximate_progress(self) -> float:
        # The denominator grows as the tree is discovered, so this is intentionally approximate.
        return self.processed_dirs / max(1, self.discovered_dirs)
