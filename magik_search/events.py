from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any


class EventStream:
    """Async structured event sink with a bounded in-memory backtrace."""

    def __init__(self, path: Path, run_id: str, ring_size: int = 512) -> None:
        self.path = path
        self.run_id = run_id
        self.ring: deque[dict[str, Any]] = deque(maxlen=ring_size)
        self.count = 0
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=8192)
        self._lock = threading.Lock()
        self._error: BaseException | None = None
        self._closed = False
        # Fail synchronously before traversal starts if the log is not writable.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8"):
            pass
        self._thread = threading.Thread(target=self._write_loop, name="event-writer", daemon=True)
        self._thread.start()

    def emit(self, kind: str, **data: Any) -> None:
        event = {"ts": time.time(), "mono_ns": time.monotonic_ns(), "run_id": self.run_id, "kind": kind, **data}
        while True:
            with self._lock:
                if self._closed or self._error is not None:
                    return
            try:
                self._queue.put(event, timeout=0.1)
                break
            except queue.Full:
                if not self._thread.is_alive():
                    self._record_error(RuntimeError("event writer stopped unexpectedly"))
        with self._lock:
            self.ring.append(event)
            self.count += 1

    def _write_loop(self) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as output:
                while True:
                    event = self._queue.get()
                    try:
                        if event is None:
                            return
                        output.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
                        if self._queue.empty():
                            output.flush()
                    finally:
                        self._queue.task_done()
        except BaseException as exc:
            self._record_error(exc)

    def _record_error(self, error: BaseException) -> None:
        with self._lock:
            if self._error is None:
                self._error = error

    def _raise_if_failed(self) -> None:
        with self._lock:
            error = self._error
        if error is not None:
            raise OSError(f"event writer failed for {self.path}: {error}") from error

    def close(self) -> None:
        with self._lock:
            already_closed = self._closed
            self._closed = True
        if already_closed:
            self._raise_if_failed()
            return
        while self._thread.is_alive():
            try:
                self._queue.put(None, timeout=0.1)
                break
            except queue.Full:
                continue
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise OSError(f"event writer did not stop for {self.path}")
        self._raise_if_failed()
