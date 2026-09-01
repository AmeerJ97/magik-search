from __future__ import annotations

import fnmatch
import math
import os
import queue
import threading
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from .classifier import Classifier
from .events import EventStream
from .models import ClassifierStats, LaneStats, PhysicalDrive, Topology, WorkerStats
from .topology import synthetic_drive


@dataclass(frozen=True)
class DirectoryTask:
    path: Path
    root_device: int


class LaneRuntime:
    def __init__(self, stats: LaneStats) -> None:
        self.stats = stats
        self.tasks: queue.Queue[DirectoryTask] = queue.Queue()
        self.candidates: queue.Queue[Path | None] = queue.Queue(maxsize=4096)
        self.done = threading.Event()
        self.workers: dict[str, threading.Thread] = {}
        self.worker_stats: list[WorkerStats] = []
        self.classifier_stats: list[ClassifierStats] = []


class Scanner:
    def __init__(
        self,
        topology: Topology,
        roots: Iterable[Path],
        patterns: list[str],
        events: EventStream,
        classifier: Classifier,
        *,
        ssd_workers: int = 4,
        hdd_workers: int = 1,
        batch_size: int = 64,
        cross_filesystems: bool = False,
        temp_limit: float = 80.0,
        excluded_paths: Iterable[Path] = (),
    ) -> None:
        self.topology = topology
        self.patterns = [pattern.casefold() for pattern in patterns]
        self.events = events
        self.classifier = classifier
        self.batch_size = max(1, batch_size)
        self.cross_filesystems = cross_filesystems
        self.temp_limit = temp_limit
        self.excluded_paths = tuple(path.expanduser().resolve() for path in excluded_paths)
        self.stop = threading.Event()
        self.interrupted = False
        self.started_at = time.time()
        self.ended_at: float | None = None
        self.temp_c: float | None = None
        self.load_1m = 0.0
        self.results: list[dict[str, object]] = []
        self._result_lock = threading.Lock()
        self._mount_roots = {
            Path(mount.target).expanduser().resolve()
            for mount in self.topology.mounts
            if Path(mount.target).expanduser().is_dir()
        }
        prepared_roots = self._prepare_roots(roots)
        self._managed_roots = set(prepared_roots)
        self.lanes = self._make_lanes(prepared_roots, ssd_workers, hdd_workers)

    def _make_lanes(self, roots: Iterable[Path], ssd_workers: int, hdd_workers: int) -> list[LaneRuntime]:
        grouped: dict[str, tuple[PhysicalDrive, list[Path]]] = {}
        for root in roots:
            names = self.topology.drives_for(root)
            if not names:
                drive = synthetic_drive(root)
                names = (drive.name,)
            else:
                drive = self.topology.drives[names[0]]
            # Multi-PV filesystems intentionally share one composite lane.
            lane_name = "+".join(names)
            if len(names) > 1:
                drive = PhysicalDrive(
                    lane_name,
                    "+".join(self.topology.drives[n].path for n in names),
                    any(self.topology.drives[n].rotational for n in names),
                    sum(self.topology.drives[n].size for n in names),
                    "multi-device",
                )
            grouped.setdefault(lane_name, (drive, []))[1].append(root)
        lanes: list[LaneRuntime] = []
        for _, (drive, lane_roots) in sorted(grouped.items()):
            maximum = max(1, hdd_workers if drive.rotational else ssd_workers)
            stats = LaneStats(
                drive=drive,
                roots=[str(root) for root in lane_roots],
                max_workers=maximum,
                allowed_workers=maximum,
            )
            runtime = LaneRuntime(stats)
            for root in lane_roots:
                runtime.tasks.put(DirectoryTask(root, root.stat().st_dev))
                stats.discovered_dirs += 1
            lanes.append(runtime)
        return lanes

    def _prepare_roots(self, roots: Iterable[Path]) -> list[Path]:
        requested: list[Path] = []
        for supplied in roots:
            root = supplied.expanduser().resolve()
            if not root.is_dir():
                raise ValueError(f"scan root is not a directory: {root}")
            if root not in requested:
                requested.append(root)
        nested_mounts = sorted(
            {
                mount_root
                for mount_root in self._mount_roots
                if any(mount_root != root and root in mount_root.parents for root in requested)
            },
            key=str,
        )
        prepared = self._normalized_roots([*requested, *nested_mounts])
        self.requested_roots = requested
        self.expanded_mount_roots = [root for root in prepared if root not in requested]
        return prepared

    def _normalized_roots(self, roots: Iterable[Path]) -> list[Path]:
        """Remove roots already covered by another traversal without crossing a device boundary."""
        normalized: list[tuple[Path, int]] = []
        for supplied in roots:
            root = supplied.expanduser().resolve()
            if not root.is_dir():
                raise ValueError(f"scan root is not a directory: {root}")
            device = root.stat().st_dev
            if any(
                existing == root
                or (
                    existing in root.parents
                    and existing_device == device
                    and root not in self._mount_roots
                    and self.topology.drives_for(existing) == self.topology.drives_for(root)
                )
                for existing, existing_device in normalized
            ):
                continue
            normalized = [
                (existing, existing_device)
                for existing, existing_device in normalized
                if not (
                    root in existing.parents
                    and existing_device == device
                    and existing not in self._mount_roots
                    and self.topology.drives_for(existing) == self.topology.drives_for(root)
                )
            ]
            normalized.append((root, device))
        return [root for root, _ in normalized]

    def run(self) -> dict[str, object]:
        self.events.emit(
            "run_started",
            roots=[root for lane in self.lanes for root in lane.stats.roots],
            requested_roots=[str(root) for root in self.requested_roots],
            expanded_mount_roots=[str(root) for root in self.expanded_mount_roots],
            patterns=self.patterns,
            topology=self.topology.as_dict(),
        )
        threads: list[threading.Thread] = []
        for lane in self.lanes:
            manager = threading.Thread(target=self._manage_lane, args=(lane,), name=f"manager-{lane.stats.drive.name}")
            classifier = threading.Thread(
                target=self._classify_lane, args=(lane,), name=f"classifier-{lane.stats.drive.name}"
            )
            manager.start()
            classifier.start()
            threads.extend((manager, classifier))
        monitor = threading.Thread(target=self._monitor_resources, name="resource-monitor")
        monitor.start()
        try:
            for thread in threads:
                thread.join()
        except KeyboardInterrupt:
            self.interrupted = True
            self.stop.set()
            for thread in threads:
                thread.join(timeout=3)
        self.stop.set()
        monitor.join(timeout=2)
        self.ended_at = time.time()
        summary = self.summary()
        # The final lifecycle event carries the summary, so account for that
        # event in both the embedded and returned summary before emitting it.
        summary["events"] = self.events.count + 1
        self.events.emit("run_finished", summary=summary)
        return summary

    def request_stop(self) -> None:
        self.stop.set()

    def _manage_lane(self, lane: LaneRuntime) -> None:
        stats = lane.stats
        stats.status = "scanning"
        while not self.stop.is_set():
            with stats.lock:
                alive = {key: thread for key, thread in lane.workers.items() if thread.is_alive()}
                lane.workers = alive
                stats.active_workers = len(alive)
                backlog = lane.tasks.qsize()
                desired = min(
                    stats.allowed_workers,
                    stats.max_workers,
                    max(1, 1 + int(math.log2(max(1, backlog)))),
                )
                needed = max(0, desired - len(alive))
            for _ in range(needed):
                worker_id = f"scout-{stats.drive.name}-{stats.spawned_workers + 1}"
                worker_stat = WorkerStats(worker_id=worker_id, drive=stats.drive.name)
                thread = threading.Thread(target=self._scan_worker, args=(lane, worker_stat), name=worker_id)
                with stats.lock:
                    stats.spawned_workers += 1
                    lane.worker_stats.append(worker_stat)
                    lane.workers[worker_id] = thread
                self.events.emit("worker_spawned", worker_id=worker_id, drive=stats.drive.name)
                thread.start()
            if lane.tasks.unfinished_tasks == 0:
                lane.done.set()
                break
            time.sleep(0.1)
        for thread in list(lane.workers.values()):
            thread.join(timeout=2)
        stats.status = "stopped" if self.stop.is_set() else "complete"
        lane.candidates.put(None)

    def _scan_worker(self, lane: LaneRuntime, worker: WorkerStats) -> None:
        stats = lane.stats
        try:
            while not self.stop.is_set() and not lane.done.is_set():
                try:
                    task = lane.tasks.get(timeout=0.25)
                except queue.Empty:
                    if lane.tasks.unfinished_tasks == 0:
                        return
                    continue
                try:
                    self._scan_directory(lane, worker, task)
                finally:
                    lane.tasks.task_done()
        finally:
            worker.ended_at = time.time()
            with stats.lock:
                stats.current_paths.pop(worker.worker_id, None)
            self.events.emit(
                "worker_finished",
                **asdict(worker),
                duration=worker.duration,
                coverage=worker.coverage,
                usefulness=worker.usefulness,
            )

    def _scan_directory(self, lane: LaneRuntime, worker: WorkerStats, task: DirectoryTask) -> None:
        stats = lane.stats
        path = task.path
        while not self.stop.is_set() and not self._worker_permitted(lane, worker.worker_id):
            time.sleep(0.1)
        if self.stop.is_set():
            return
        with stats.lock:
            stats.current_paths[worker.worker_id] = str(path)
            stats.recent_paths.append(str(path))
            del stats.recent_paths[:-40]
        self.events.emit("directory_opened", path=str(path), drive=stats.drive.name, worker_id=worker.worker_id)
        worker.directories += 1
        try:
            entries = list(os.scandir(path))
        except OSError as exc:
            worker.errors += 1
            with stats.lock:
                stats.errors += 1
            self.events.emit(
                "scan_error", path=str(path), error=f"{type(exc).__name__}: {exc}", worker_id=worker.worker_id
            )
            with stats.lock:
                stats.processed_dirs += 1
            return
        for entry in entries:
            if self.stop.is_set():
                break
            try:
                entry_path = Path(entry.path)
                if self._is_excluded(entry_path):
                    self.events.emit(
                        "entry_excluded",
                        path=entry.path,
                        drive=stats.drive.name,
                        worker_id=worker.worker_id,
                    )
                    continue
                info = entry.stat(follow_symlinks=False)
                is_dir = entry.is_dir(follow_symlinks=False)
                metadata = {
                    "path": entry.path,
                    "name": entry.name,
                    "size": info.st_size,
                    "mtime_ns": info.st_mtime_ns,
                    "mode": info.st_mode,
                    "inode": info.st_ino,
                    "device": info.st_dev,
                    "drive": stats.drive.name,
                    "worker_id": worker.worker_id,
                }
                self.events.emit("directory_seen" if is_dir else "file_seen", **metadata)
                worker.entries += 1
                with stats.lock:
                    stats.entries += 1
                if is_dir:
                    if entry_path in self._managed_roots:
                        self.events.emit(
                            "mount_delegated",
                            path=entry.path,
                            drive=stats.drive.name,
                            target_drives=self.topology.drives_for(entry_path),
                            worker_id=worker.worker_id,
                        )
                    elif self.cross_filesystems or info.st_dev == task.root_device:
                        lane.tasks.put(DirectoryTask(Path(entry.path), task.root_device))
                        with stats.lock:
                            stats.discovered_dirs += 1
                if any(fnmatch.fnmatch(entry.name.casefold(), pattern) for pattern in self.patterns):
                    worker.candidates += 1
                    with stats.lock:
                        stats.candidates += 1
                    self.events.emit("candidate_seen", **metadata)
                    lane.candidates.put(Path(entry.path))
            except OSError as exc:
                worker.errors += 1
                with stats.lock:
                    stats.errors += 1
                self.events.emit(
                    "metadata_error", path=entry.path, error=f"{type(exc).__name__}: {exc}", worker_id=worker.worker_id
                )
        with stats.lock:
            stats.processed_dirs += 1

    def _is_excluded(self, path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved == excluded or excluded in resolved.parents for excluded in self.excluded_paths)

    @staticmethod
    def _worker_permitted(lane: LaneRuntime, worker_id: str) -> bool:
        """Gate already-running workers when per-drive pressure lowers capacity."""
        with lane.stats.lock:
            live_ids = sorted(key for key, thread in lane.workers.items() if thread.is_alive())
            try:
                rank = live_ids.index(worker_id)
            except ValueError:
                return False
            return rank < lane.stats.allowed_workers

    def _classify_lane(self, lane: LaneRuntime) -> None:
        batch: list[Path] = []
        while True:
            item = lane.candidates.get()
            try:
                if item is None:
                    if batch:
                        self._classify_batch(lane, batch)
                    return
                batch.append(item)
                if len(batch) >= self.batch_size:
                    self._classify_batch(lane, batch)
                    batch = []
            finally:
                lane.candidates.task_done()

    def _classify_batch(self, lane: LaneRuntime, paths: list[Path]) -> None:
        results, invocation = self.classifier.classify(paths)
        lane.classifier_stats.append(invocation)
        verified = sum(bool(result["verified"]) for result in results)
        with lane.stats.lock:
            lane.stats.matches += verified
        with self._result_lock:
            self.results.extend(results)
        self.events.emit(
            "classifier_finished",
            **asdict(invocation),
            duration=invocation.ended_at - invocation.started_at,
            results=results,
        )

    def _monitor_resources(self) -> None:
        previous = self._diskstats()
        previous_at = time.monotonic()
        while not self.stop.wait(0.5):
            current = self._diskstats()
            now = time.monotonic()
            elapsed_ms = max(1.0, (now - previous_at) * 1000)
            self.temp_c = self._cpu_temp()
            try:
                self.load_1m = os.getloadavg()[0]
            except OSError:
                self.load_1m = 0.0
            thermal = self.temp_c is not None and self.temp_c >= self.temp_limit
            for lane in self.lanes:
                names = lane.stats.drive.name.split("+")
                delta = max(
                    (max(0, current.get(name, 0) - previous.get(name, 0)) for name in names),
                    default=0,
                )
                pressure = min(1.0, delta / elapsed_ms)
                with lane.stats.lock:
                    lane.stats.io_pressure = pressure
                    if thermal:
                        lane.stats.allowed_workers = 0
                        lane.stats.status = "thermal throttle"
                    elif pressure >= 0.90:
                        lane.stats.allowed_workers = 1
                        lane.stats.status = "I/O throttle"
                    else:
                        lane.stats.allowed_workers = lane.stats.max_workers
                        if lane.stats.status.endswith("throttle"):
                            lane.stats.status = "scanning"
            self.events.emit(
                "resource_sample",
                temp_c=self.temp_c,
                load_1m=self.load_1m,
                lanes={
                    lane.stats.drive.name: {
                        "io_pressure": lane.stats.io_pressure,
                        "allowed_workers": lane.stats.allowed_workers,
                    }
                    for lane in self.lanes
                },
            )
            previous, previous_at = current, now

    @staticmethod
    def _diskstats() -> dict[str, int]:
        values: dict[str, int] = {}
        try:
            with open("/proc/diskstats", encoding="ascii") as source:
                for line in source:
                    fields = line.split()
                    if len(fields) >= 14:
                        values[fields[2]] = int(fields[12])  # milliseconds with I/O in progress
        except OSError:
            pass
        return values

    @staticmethod
    def _cpu_temp() -> float | None:
        temperatures: list[float] = []
        for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            try:
                value = float(path.read_text().strip())
                temperatures.append(value / 1000 if value > 1000 else value)
            except (OSError, ValueError):
                continue
        return max(temperatures) if temperatures else None

    def summary(self) -> dict[str, object]:
        workers = [worker for lane in self.lanes for worker in lane.worker_stats]
        invocations = [item for lane in self.lanes for item in lane.classifier_stats]
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration": (self.ended_at or time.time()) - self.started_at,
            "interrupted": self.interrupted,
            "requested_roots": [str(root) for root in self.requested_roots],
            "expanded_mount_roots": [str(root) for root in self.expanded_mount_roots],
            "events": self.events.count,
            "results": len(self.results),
            "verified_matches": sum(bool(item["verified"]) for item in self.results),
            "workers": {
                "spawned": len(workers),
                "aggregate_lifetime": sum(worker.duration for worker in workers),
                "coverage": sum(worker.coverage for worker in workers),
                "usefulness": sum(worker.candidates for worker in workers)
                / max(1, sum(worker.entries for worker in workers)),
                "items": [
                    {
                        **asdict(worker),
                        "duration": worker.duration,
                        "coverage": worker.coverage,
                        "usefulness": worker.usefulness,
                    }
                    for worker in workers
                ],
            },
            "magika_invocations": {
                "spawned": len(invocations),
                "aggregate_lifetime": sum(item.ended_at - item.started_at for item in invocations),
                "coverage": sum(item.candidates for item in invocations),
                "usefulness": sum(item.matches for item in invocations)
                / max(1, sum(item.candidates for item in invocations)),
                "items": [asdict(item) for item in invocations],
            },
            "lanes": [self._lane_summary(lane) for lane in self.lanes],
        }

    @staticmethod
    def _lane_summary(lane: LaneRuntime) -> dict[str, object]:
        stats = lane.stats
        with stats.lock:
            return {
                "drive": asdict(stats.drive),
                "roots": list(stats.roots),
                "max_workers": stats.max_workers,
                "allowed_workers": stats.allowed_workers,
                "active_workers": stats.active_workers,
                "spawned_workers": stats.spawned_workers,
                "discovered_dirs": stats.discovered_dirs,
                "processed_dirs": stats.processed_dirs,
                "entries": stats.entries,
                "candidates": stats.candidates,
                "matches": stats.matches,
                "errors": stats.errors,
                "io_pressure": stats.io_pressure,
                "status": stats.status,
                "approximate_progress": stats.approximate_progress,
            }
