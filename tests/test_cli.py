import json
from pathlib import Path

import pytest

from magik_search import __version__
from magik_search.cli import main


def test_version(capsys) -> None:
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert capsys.readouterr().out.strip() == f"magik-search {__version__}"


def test_stats_human_output(tmp_path: Path, capsys) -> None:
    summary = {
        "duration": 1.25,
        "results": 4,
        "verified_matches": 2,
        "events": 10,
        "workers": {"spawned": 2, "coverage": 20, "usefulness": 0.2},
        "magika_invocations": {"spawned": 1, "coverage": 4, "usefulness": 0.5},
        "lanes": [
            {
                "drive": {"name": "nvme0n1"},
                "entries": 18,
                "candidates": 4,
                "spawned_workers": 2,
                "errors": 0,
            }
        ],
    }
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary))
    assert main(["stats", str(path)]) == 0
    output = capsys.readouterr().out
    assert "Run complete in 1.25s" in output
    assert "nvme0n1" in output


def test_stats_invalid_file_has_operator_error(tmp_path: Path, capsys) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{}")
    assert main(["stats", str(path)]) == 2
    assert "not a magik-search summary" in capsys.readouterr().err


def test_scan_rejects_invalid_worker_count() -> None:
    try:
        main(["scan", "--ssd-workers", "0"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("argparse should reject zero workers")


def test_scan_rejects_missing_root_without_creating_output(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["scan", "missing", "--no-tui"]) == 2
    assert "scan root is not a directory" in capsys.readouterr().err
    assert not (tmp_path / "magik-runs").exists()


@pytest.mark.skipif(not Path("/dev/full").exists(), reason="Linux full-device fixture is unavailable")
def test_scan_reports_event_log_failure(tmp_path: Path, capsys) -> None:
    assert (
        main(
            [
                "scan",
                str(tmp_path),
                "--no-magika",
                "--no-tui",
                "--event-log",
                "/dev/full",
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 2
    )
    assert "event writer failed" in capsys.readouterr().err
