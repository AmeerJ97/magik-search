import json
import shutil
from pathlib import Path

import pytest

from magik_search import __version__
from magik_search.cli import main
from magik_search.models import Topology


def _summary() -> dict:
    return {
        "duration": 1.25,
        "results": 4,
        "verified_matches": 2,
        "events": 10,
        "workers": {"spawned": 2, "coverage": 20, "usefulness": 0.00001},
        "magika_invocations": {"spawned": 1, "coverage": 4, "usefulness": 0.5},
        "lanes": [
            {
                "drive": {"name": "nvme0n1"},
                "entries": 18,
                "candidates": 4,
                "spawned_workers": 2,
                "errors": 0,
                "status": "complete",
                "approximate_progress": 1.0,
                "io_pressure": 0.1,
            }
        ],
    }


def test_version(capsys) -> None:
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert capsys.readouterr().out.strip() == f"magik-search {__version__}"


def test_stats_human_output(tmp_path: Path, capsys) -> None:
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(_summary()))
    assert main(["stats", str(path)]) == 0
    output = capsys.readouterr().out
    assert "Run complete in 1.25s" in output
    assert "nvme0n1" in output
    assert "<0.01% useful" in output
    assert "\033[" not in output


def test_no_argument_output_has_quick_start(capsys) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "Quick start:" in output
    assert "magik-search scan /data" in output


def test_stats_finds_latest_run_and_accepts_run_directory(tmp_path: Path, monkeypatch, capsys) -> None:
    run = tmp_path / "magik-runs" / "latest"
    run.mkdir(parents=True)
    summary = run / "summary.json"
    summary.write_text(json.dumps(_summary()))
    monkeypatch.chdir(tmp_path)

    assert main(["stats"]) == 0
    assert str(summary.relative_to(tmp_path)) in capsys.readouterr().out
    assert main(["stats", str(run)]) == 0
    assert str(summary) in capsys.readouterr().out


def test_stats_json_stays_machine_readable(tmp_path: Path, capsys) -> None:
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(_summary()))
    assert main(["stats", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["results"] == 4


def test_doctor_reports_probe_and_classifier_warnings(monkeypatch, capsys) -> None:
    monkeypatch.setattr("magik_search.cli.discover_topology", lambda: Topology({}, [], warnings=["pvs probe failed"]))
    monkeypatch.setattr(shutil, "which", lambda command: f"/usr/bin/{command}")

    class MetadataClassifier:
        backend = "metadata"
        unavailable_reason = "Magika is not installed"

    monkeypatch.setattr("magik_search.cli.Classifier", MetadataClassifier)
    assert main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "pvs probe failed" in output
    assert "Magika is not installed" in output
    assert "Ready to scan with 2 warning(s)." in output


def test_topology_separates_human_warnings_from_output(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "magik_search.cli.discover_topology",
        lambda: Topology({}, [], warnings=["pvs probe failed (permission denied)"]),
    )
    assert main(["topology"]) == 0
    captured = capsys.readouterr()
    assert "Physical drives (0)" in captured.out
    assert "pvs probe failed" not in captured.out
    assert "pvs probe failed" in captured.err


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
