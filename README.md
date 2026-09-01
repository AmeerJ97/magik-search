# magik-search

Drive-aware filesystem discovery for Linux. `magik-search` maps requested roots
to their physical disks, grows traversal concurrency with the work backlog,
throttles each drive independently, and shows the discovered filesystem as a
live colored terminal tree.

It began as an XML/FSM finder, but the search engine is intentionally general:
use one or more case-insensitive entry-name globs and scan any set of roots.
Matching files and directories are both returned; directories are always
metadata-only results and continue to be traversed.

## Highlights

- Discovers disks, mounts, LVM physical volumes, and logical volumes at runtime.
- Expands nested mounts beneath a requested root and schedules each one in its
  physical drive's lane.
- Keeps rotational disks sequential by default while allowing SSD/NVMe
  concurrency.
- Spawns traversal scouts dynamically as useful work becomes available.
- Responds to per-drive I/O pressure and global CPU temperature.
- Logs metadata for every observed entry without logging file content.
- Optionally verifies candidate types in batches with Google Magika.
- Draws a live colored tree above approximate progress bars for every drive.
- Records scout and classifier spawn count, lifetime, coverage, usefulness, and
  errors for later analysis.
- Has no required third-party Python runtime dependencies.

## When to use it

For an ordinary lookup inside one repository, `fd`, `find`, or `rg --files` is
usually the simpler and faster choice. `magik-search` is intended for broad or
multi-root Linux discovery where physical-drive-aware concurrency, conservative
filesystem boundaries, and a reusable telemetry trail are useful.

It is a focused community utility rather than an indexed search service: every
run performs a fresh traversal, and performance depends on the directory shape,
storage topology, requested patterns, and logging volume.

## Requirements

- Linux
- Python 3.10 or newer
- `lsblk` and `findmnt` from util-linux
- Optional: LVM2's `pvs` and `lvs` for richer LVM reports
- Optional: Magika for content-type verification

Missing optional tools are reported but do not prevent scanning.

## Install

After cloning or downloading the repository, run the isolated user installer:

```bash
cd magik-search
./scripts/install.sh
magik-search doctor
```

Include Magika classification:

```bash
./scripts/install.sh --with-magika
```

The installer creates an isolated virtual environment under
`$XDG_DATA_HOME/magik-search` (normally `~/.local/share/magik-search`) and links
the CLI into `$XDG_BIN_HOME` (normally `~/.local/bin`). It does not use `sudo`.

Other standard installation methods work too:

```bash
pipx install .
pipx install '.[magika]'

# or, inside an activated virtual environment
python -m pip install .
```

Uninstall an installation made by the bundled script:

```bash
./scripts/uninstall.sh
```

Scan outputs are never removed by the uninstaller.

## Quick start

Inspect the topology the scheduler will use:

```bash
magik-search topology
magik-search topology --json
```

Search for the original FSM/XML target:

```bash
magik-search scan /home/core /home/files
```

Search using generalized patterns:

```bash
magik-search scan /data /archive \
  -g '*.xml' \
  -g '*.json' \
  --ssd-workers 6 \
  --hdd-workers 1 \
  --batch-size 128
```

Each run writes to `magik-runs/<timestamp-id>/` by default:

```text
events.jsonl   append-only observation and lifecycle events
results.jsonl  one classification result per candidate path
summary.json  aggregate and per-lifecycle statistics
```

View a completed run:

```bash
magik-search stats magik-runs/20260812-120000-ab12cd34/summary.json
```

## Important scan options

| Option | Meaning |
| --- | --- |
| `-g`, `--name-glob GLOB` | Candidate file or directory name glob; repeatable |
| `--ssd-workers N` | Maximum scouts per SSD/NVMe; default 4 |
| `--hdd-workers N` | Maximum scouts per rotational disk; default 1 |
| `--batch-size N` | Candidate paths per classifier invocation |
| `--no-magika` | Metadata-only scan; never read candidate content |
| `--no-tui` | Plain output for automation and logs |
| `--cross-filesystems` | Also cross device boundaries missing from discovered topology |
| `--output-dir DIR` | Place run artifacts in a chosen directory |
| `--results FILE` | Override the candidate-results JSONL path |
| `--temp-limit °C` | Pause new directory work at this temperature |

Run `magik-search scan --help` for the complete and current interface.

## Progress and statistics

Drive progress is approximate: processed directories divided by directories
discovered so far. It may briefly move backward when a directory reveals more
children. An exact percentage would require a full pre-scan and double the
filesystem metadata I/O.

Scout usefulness is candidate yield per observed entry. Classifier usefulness
is verified matches per submitted candidate. Individual lifecycle data is
preserved in the summary so runs can later be compared by drive type, worker
policy, pressure, duration, or search pattern.

## Privacy and safety

Events contain filesystem paths and metadata and should be protected like an
inventory. They never contain file bytes. Only the optional classifier reads
candidate content; pass `--no-magika` to guarantee metadata-only operation.

The scanner does not traverse symbolic-link directories. Known nested mounts
are promoted to independent roots and grouped by physical drive; each lane then
stays on its assigned filesystem. `--cross-filesystems` additionally permits
crossing boundaries that were not represented by discovered topology.
Symlinked file candidates remain visible as metadata results but are never sent
to Magika for content reads. The scanner's own output directory and files are
excluded from traversal.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
ruff format --check .
python -m build
```

Architecture and event-schema details live in [report.md](report.md).
Pragmatic future work and the boundary with experimental scheduling research
live in [ROADMAP.md](ROADMAP.md).
Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
