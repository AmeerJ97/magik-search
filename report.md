# magik-search 0.3 — drive-aware filesystem discovery

`magik-search` is now a general filesystem discovery project. It is not tied to
three named disks, fixed mountpoints, XML, or a fixed worker count. Its small
external interface is the `doctor`, `topology`, `scan`, and `stats` commands; physical-drive
mapping, adaptive scheduling, event capture, classification, and presentation
remain behind that seam.

## What it does

1. Calls Linux storage CLIs rather than trusting a static configuration:
   `lsblk --json`, `findmnt --json`, and, when accessible, `pvs`/`lvs` JSON
   reports.
2. Walks the block tree from a mount or LVM logical volume back to its physical
   disk. Multi-PV filesystems become a composite lane so they are never given
   independent per-mount worker pools by mistake.
3. Expands nested mountpoints beneath requested roots, then groups all resulting
   filesystem roots by physical drive. Rotational drives default to one worker;
   SSD/NVMe drives default to four. Both values are CLI options.
4. Spawns short-lived traversal workers as the discovered directory backlog
   grows. Existing workers are gated when that drive's weighted I/O time shows
   saturation. Thermal throttling is global, while I/O throttling is per drive.
5. Emits a JSONL event for every observed filesystem entry. Name patterns match
   both files and directories, with directories retained as metadata-only
   candidates while traversal continues. A file event
   contains path, name, size, mtime, mode, inode, device, drive, and worker—never
   file content. Only candidate paths may be read by the optional Magika adapter.
6. Renders an ANSI live dashboard with one approximate progress bar per drive,
   current worker limits, I/O pressure, and a colored tree made from recently
   discovered paths.
7. Writes a JSON summary with traversal-worker and classifier-invocation spawn
   counts, lifetime, coverage, and usefulness.

The event module follows the useful ideas from the local `spdlog` and
`envlogger` references: an asynchronous sink, bounded in-memory backtrace, run
metadata, and per-step/per-lifecycle metadata. It does not require a C++ spdlog
binding. The other suggested reference projects were not used because they do
not deepen a Linux filesystem traversal or observability module.

## Commands

Inspect what the CLI discovers:

```bash
python3 magik-search.py topology
python3 magik-search.py topology --json
```

Scan one or more roots with the original search behavior:

```bash
python3 magik-search.py scan /home/core /home/files \
  --name-glob '*fsm*.xml'
```

Use generalized patterns and tune physical media independently:

```bash
python3 magik-search.py scan /data /archive \
  --name-glob '*.xml' \
  --name-glob '*.json' \
  --ssd-workers 6 \
  --hdd-workers 1 \
  --batch-size 128 \
  --event-log run/events.jsonl \
  --results run/results.jsonl \
  --summary run/summary.json
```

Useful controls:

- `--no-magika` guarantees metadata-only operation and never reads candidate
  content.
- `--no-tui` is suitable for cron, pipes, and tests. The dashboard also disables
  itself automatically when stdout is not a terminal.
- `--cross-filesystems` opts into crossing mount/device seams. The safe default
  keeps each root on its starting filesystem.
- `--temp-limit` sets the high-temperature gate. If thermal sensors are not
  exposed, per-drive I/O throttling still operates.

Magika is optional:

```bash
python3 -m pip install -e '.[magika]'
```

Without Magika, candidates are retained as unverified metadata results rather
than falsely reported as confirmed XML.

## Live model

```text
storage CLIs ──► topology ──► roots grouped by physical drive
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
                drive lane      drive lane      drive lane
              dynamic scouts  dynamic scouts  dynamic scouts
                    └───────────────┬───────────────┘
                                    ▼
                              candidate batches
                                    ▼
                         Magika or metadata adapter

every observation ──► async JSONL stream ──► statistics
         └──────────► bounded live ring ────► colored TUI tree
```

Approximate progress is `processed directories / directories discovered so
far`. It can move backward when a directory reveals more children; the `≈`
marker in the dashboard makes that uncertainty explicit. Computing an exact
percentage would require a wasteful full pre-walk and double the metadata I/O.

## Statistics semantics

Traversal workers are called `scouts` in event IDs:

- **spawned** — total scout lifecycles, including replacements.
- **lifetime** — wall time from spawn through retirement.
- **coverage** — directories processed plus entries observed.
- **usefulness** — candidate paths divided by entries observed.

Classifier batches use `magika-*` invocation IDs even when the metadata adapter
is active, so run schemas remain comparable:

- **spawned** — classifier batch invocations.
- **lifetime** — time spent classifying all batches.
- **coverage** — candidate paths submitted.
- **usefulness** — verified matches divided by submitted candidates.

The summary preserves every lifecycle item, not just aggregates, so later runs
can compute distributions, correlations with drive pressure, and scheduler
policy changes without changing the scanner.

## Output and privacy

`events.jsonl` is append-only structured telemetry. Each event has wall
time, monotonic time, run ID, kind, and kind-specific metadata. It can reveal
filenames and directory structure, so protect it like an inventory. File bytes
are never logged.

`results.jsonl` contains one candidate classification result per line, including
path, label, MIME type, score, and verification state. `summary.json` contains
topology-independent run metrics and lifecycle aggregates. All output paths are
configurable and excluded from the traversal that creates them.

## Verification

```bash
python3 -m compileall -q magik_search magik-search.py
python3 -m pytest -q
```

The tests cover LVM-to-physical-disk mapping, multi-PV aggregation, metadata
event capture, candidate batching, and lifecycle statistics.
