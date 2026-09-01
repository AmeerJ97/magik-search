from pathlib import Path

from magik_search.topology import topology_from_reports


def test_lvm_mount_maps_to_physical_disk() -> None:
    report = {
        "blockdevices": [
            {
                "name": "sda",
                "path": "/dev/sda",
                "type": "disk",
                "rota": 1,
                "size": 1000,
                "children": [
                    {
                        "name": "sda1",
                        "path": "/dev/sda1",
                        "type": "part",
                        "children": [
                            {
                                "name": "vg-home",
                                "path": "/dev/mapper/vg-home",
                                "type": "lvm",
                                "mountpoints": ["/home"],
                                "fstype": "ext4",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    topology = topology_from_reports(report)
    assert topology.drives_for(Path("/home/core/project")) == ("sda",)
    assert topology.drives["sda"].rotational is True


def test_multi_pv_mount_aggregates_drives() -> None:
    logical = {"name": "vg-data", "path": "/dev/mapper/vg-data", "type": "lvm", "mountpoints": ["/data"]}
    report = {
        "blockdevices": [
            {"name": "sda", "type": "disk", "rota": 1, "children": [logical]},
            {"name": "sdb", "type": "disk", "rota": 1, "children": [logical]},
        ]
    }
    topology = topology_from_reports(report)
    assert topology.drives_for(Path("/data/archive")) == ("sda", "sdb")
