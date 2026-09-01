from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .models import ClassifierStats


class Classifier:
    """One narrow classification seam; Magika and metadata-only adapters live behind it."""

    def __init__(self, enabled: bool = True) -> None:
        self._lock = threading.Lock()
        self._magika: Any = None
        self.backend = "metadata"
        if enabled:
            try:
                from magika import Magika

                self._magika = Magika()
                self.backend = "magika"
            except Exception:
                pass

    def classify(self, paths: list[Path]) -> tuple[list[dict[str, Any]], ClassifierStats]:
        started = time.time()
        invocation_id = f"magika-{uuid.uuid4().hex[:10]}"
        classified: dict[Path, dict[str, Any]] = {}
        error: str | None = None
        if self._magika:
            try:
                content_paths = [path for path in paths if not path.is_symlink() and not path.is_dir()]
                if content_paths:
                    with self._lock:
                        results = self._magika.identify_paths([str(path) for path in content_paths])
                    for path, result in zip(content_paths, results, strict=True):
                        item = result.output
                        label = str(item.ct_label)
                        mime = str(item.mime_type)
                        classified[path] = {
                            "path": str(path),
                            "label": label,
                            "mime": mime,
                            "score": float(item.score),
                            "verified": label in {"xml", "svg"} or "xml" in mime.lower(),
                        }
            except Exception as exc:  # Classifier failure must not terminate traversal.
                error = f"{type(exc).__name__}: {exc}"
        if error:
            classified.clear()
        output = [classified[path] if path in classified else self._metadata_result(path) for path in paths]
        ended = time.time()
        stats = ClassifierStats(
            invocation_id=invocation_id,
            started_at=started,
            ended_at=ended,
            candidates=len(paths),
            matches=sum(bool(item["verified"]) for item in output),
            backend=self.backend,
            error=error,
        )
        return output, stats

    @staticmethod
    def _metadata_result(path: Path) -> dict[str, Any]:
        is_symlink = path.is_symlink()
        is_directory = path.is_dir() and not is_symlink
        is_xml = path.suffix.lower() == ".xml" and not is_symlink and not is_directory
        return {
            "path": str(path),
            "label": (
                "symlink-candidate"
                if is_symlink
                else ("directory" if is_directory else ("xml-candidate" if is_xml else "candidate"))
            ),
            "mime": "inode/directory" if is_directory else ("application/xml" if is_xml else "unknown"),
            "score": None,
            "verified": False,
        }
