import sys
from pathlib import Path

from magik_search.classifier import Classifier


class FailingMagika:
    def identify_paths(self, paths: list[str]) -> list[object]:
        raise AssertionError(f"symlink targets must not be classified: {paths}")


def test_magika_treats_symlink_candidates_as_metadata_only(tmp_path: Path) -> None:
    target = tmp_path / "outside.xml"
    target.write_text("<secret/>\n")
    link = tmp_path / "candidate.xml"
    link.symlink_to(target)
    classifier = Classifier(enabled=False)
    classifier._magika = FailingMagika()
    classifier.backend = "magika"

    results, stats = classifier.classify([link])

    assert results == [
        {
            "path": str(link),
            "label": "symlink-candidate",
            "mime": "unknown",
            "score": None,
            "verified": False,
        }
    ]
    assert stats.error is None


def test_missing_magika_exposes_fallback_reason(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "magika", None)
    classifier = Classifier()
    assert classifier.requested is True
    assert classifier.backend == "metadata"
    assert classifier.unavailable_reason == "Magika is not installed"


def test_explicit_metadata_mode_has_no_failure_reason() -> None:
    classifier = Classifier(enabled=False)
    assert classifier.requested is False
    assert classifier.backend == "metadata"
    assert classifier.unavailable_reason is None
