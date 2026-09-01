from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from .scanner import Scanner

RESET = "\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
DIM = "\033[2m"


def _bar(value: float, width: int = 22) -> str:
    filled = min(width, max(0, round(value * width)))
    return f"{GREEN}{'━' * filled}{DIM}{'─' * (width - filled)}{RESET}"


def _tree(paths: list[str], limit: int = 12) -> list[str]:
    root: dict[str, dict] = {}
    for path in paths[-limit:]:
        node = root
        for part in Path(path).parts:
            node = node.setdefault(part, {})
    lines: list[str] = []

    def draw(node: dict[str, dict], prefix: str = "", depth: int = 0) -> None:
        if len(lines) >= limit:
            return
        entries = list(node.items())
        for index, (name, child) in enumerate(entries):
            last = index == len(entries) - 1
            color = (CYAN, MAGENTA, YELLOW)[depth % 3]
            lines.append(f"{prefix}{'└─' if last else '├─'} {color}{name}{RESET}")
            draw(child, prefix + ("   " if last else "│  "), depth + 1)

    draw(root)
    return lines[-limit:]


class Dashboard:
    def __init__(self, scanner: Scanner, enabled: bool = True, refresh: float = 0.2) -> None:
        self.scanner = scanner
        self.enabled = enabled and sys.stdout.isatty()
        self.refresh = refresh
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="dashboard", daemon=True)

    def start(self) -> None:
        if self.enabled:
            sys.stdout.write("\033[?25l")
            self._thread.start()

    def close(self) -> None:
        if self.enabled:
            self._stop.set()
            self._thread.join(timeout=2)
            sys.stdout.write("\033[?25h\n")
            sys.stdout.flush()

    def _loop(self) -> None:
        while not self._stop.wait(self.refresh):
            temperature = self.scanner.temp_c if self.scanner.temp_c is not None else "n/a"
            roots = len(self.scanner.requested_roots)
            mounts = len(self.scanner.expanded_mount_roots)
            lines = [
                f"{CYAN}◆ magik-search live discovery{RESET}  load {self.scanner.load_1m:.2f}  temp {temperature}  "
                f"roots {roots}+{mounts} mounts"
            ]
            all_paths: list[str] = []
            for lane in self.scanner.lanes:
                stats = lane.stats
                with stats.lock:
                    progress = stats.approximate_progress
                    lines.append(
                        f"{YELLOW}◇ {stats.drive.name}{RESET} {_bar(progress)} {progress:6.1%}≈ "
                        f"workers {stats.active_workers}/{stats.allowed_workers}/{stats.max_workers} "
                        f"dirs {stats.processed_dirs}/{stats.discovered_dirs} files {stats.entries} "
                        f"candidates {stats.candidates} I/O {stats.io_pressure:3.0%} {stats.status}"
                    )
                    all_paths.extend(stats.recent_paths[-5:])
            lines.append(f"{GREEN}Live filesystem graph (recent discovery){RESET}")
            lines.extend(_tree(all_paths, max(6, min(16, os.get_terminal_size().lines - len(lines) - 2))))
            sys.stdout.write("\033[H\033[2J" + "\n".join(lines))
            sys.stdout.flush()
