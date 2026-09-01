import json
from pathlib import Path

from magik_search.classifier import Classifier
from magik_search.events import EventStream
from magik_search.models import Mount, PhysicalDrive, Topology
from magik_search.scanner import Scanner


def test_scan_records_metadata_and_statistics(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "alpha_fsm.xml").write_text("<fsm/>")
    (tmp_path / "ignore.txt").write_text("no")
    drive = PhysicalDrive("test", "/dev/test", False, 100)
    topology = Topology({"test": drive}, [Mount(str(tmp_path), "/dev/test", "ext4", ("test",))])
    event_path = tmp_path / "events.jsonl"
    events = EventStream(event_path, "test-run")
    scanner = Scanner(
        topology, [tmp_path], ["*fsm*.xml"], events, Classifier(enabled=False), ssd_workers=2, batch_size=1
    )
    summary = scanner.run()
    events.close()
    kinds = [json.loads(line)["kind"] for line in event_path.read_text().splitlines()]
    assert summary["events"] == len(kinds)
    assert summary["results"] == 1
    assert summary["workers"]["spawned"] >= 1
    assert summary["workers"]["coverage"] >= 3
    assert summary["magika_invocations"]["spawned"] == 1
    assert "file_seen" in kinds
    assert "worker_finished" in kinds


def test_single_directory_does_not_spawn_idle_scout(tmp_path: Path) -> None:
    (tmp_path / "one_fsm.xml").write_text("<fsm/>")
    drive = PhysicalDrive("test", "/dev/test", False, 100)
    topology = Topology({"test": drive}, [Mount(str(tmp_path), "/dev/test", "ext4", ("test",))])
    events = EventStream(tmp_path / "events.jsonl", "single-root")
    scanner = Scanner(
        topology,
        [tmp_path],
        ["*fsm*.xml"],
        events,
        Classifier(enabled=False),
        ssd_workers=4,
    )
    summary = scanner.run()
    events.close()
    assert summary["workers"]["spawned"] == 1


def test_repeated_and_nested_roots_are_scanned_once(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "one.py").write_text("pass\n")
    drive = PhysicalDrive("test", "/dev/test", False, 100)
    topology = Topology({"test": drive}, [Mount(str(tmp_path), "/dev/test", "ext4", ("test",))])
    events = EventStream(tmp_path / "events.jsonl", "deduplicated-roots")
    scanner = Scanner(
        topology,
        [nested, tmp_path, tmp_path],
        ["*.py"],
        events,
        Classifier(enabled=False),
    )

    summary = scanner.run()
    events.close()

    assert summary["results"] == 1
    assert [lane["roots"] for lane in summary["lanes"]] == [[str(tmp_path)]]


def test_scan_excludes_its_output_tree(tmp_path: Path) -> None:
    root = tmp_path / "root"
    output = root / "output"
    root.mkdir()
    output.mkdir()
    (root / "match.py").write_text("pass\n")
    event_path = output / "events.jsonl"
    drive = PhysicalDrive("test", "/dev/test", False, 100)
    topology = Topology({"test": drive}, [Mount(str(root), "/dev/test", "ext4", ("test",))])
    events = EventStream(event_path, "excluded-output")
    scanner = Scanner(
        topology,
        [root],
        ["*.py"],
        events,
        Classifier(enabled=False),
        excluded_paths=(output,),
    )

    summary = scanner.run()
    events.close()
    kinds = [json.loads(line)["kind"] for line in event_path.read_text().splitlines()]

    assert summary["results"] == 1
    assert "entry_excluded" in kinds


def test_nested_mounts_are_scheduled_in_physical_drive_lanes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    core = home / "core"
    media = home / "media"
    core.mkdir(parents=True)
    media.mkdir()
    (home / "root-match.txt").write_text("root\n")
    (core / "core-match.txt").write_text("core\n")
    (media / "media-match.txt").write_text("media\n")
    drives = {
        "nvme0n1": PhysicalDrive("nvme0n1", "/dev/nvme0n1", False, 100),
        "sda": PhysicalDrive("sda", "/dev/sda", True, 100),
        "sdb": PhysicalDrive("sdb", "/dev/sdb", True, 100),
    }
    topology = Topology(
        drives,
        [
            Mount(str(home), "/dev/nvme0n1p1", "ext4", ("nvme0n1",)),
            Mount(str(core), "/dev/sda1", "ext4", ("sda",)),
            Mount(str(media), "/dev/sdb1", "ext4", ("sdb",)),
        ],
    )
    events = EventStream(tmp_path / "events.jsonl", "nested-mounts")
    scanner = Scanner(topology, [home], ["*match.txt"], events, Classifier(enabled=False))

    summary = scanner.run()
    events.close()

    lanes = {lane["drive"]["name"]: lane for lane in summary["lanes"]}
    assert summary["requested_roots"] == [str(home)]
    assert summary["expanded_mount_roots"] == [str(core), str(media)]
    assert set(lanes) == {"nvme0n1", "sda", "sdb"}
    assert lanes["nvme0n1"]["roots"] == [str(home)]
    assert lanes["sda"]["roots"] == [str(core)]
    assert lanes["sdb"]["roots"] == [str(media)]
    assert summary["results"] == 3
    assert len({result["path"] for result in scanner.results}) == 3


def test_name_glob_matches_directories_and_continues_traversal(tmp_path: Path) -> None:
    project = tmp_path / "eerf-project"
    project.mkdir()
    (project / "nested.txt").write_text("data\n")
    drive = PhysicalDrive("test", "/dev/test", False, 100)
    topology = Topology({"test": drive}, [Mount(str(tmp_path), "/dev/test", "ext4", ("test",))])
    events = EventStream(tmp_path / "events.jsonl", "directory-match")
    scanner = Scanner(topology, [tmp_path], ["*eerf*"], events, Classifier(enabled=False))

    summary = scanner.run()
    events.close()

    assert summary["results"] == 1
    assert scanner.results == [
        {
            "path": str(project),
            "label": "directory",
            "mime": "inode/directory",
            "score": None,
            "verified": False,
        }
    ]
    assert summary["lanes"][0]["processed_dirs"] == 2
