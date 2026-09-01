# Roadmap

`magik-search 0.3.2` is a usable beta with topology-aware mount expansion,
per-physical-drive traversal lanes, safe filesystem boundaries, entry-name
globs, structured artifacts, and optional Magika classification.

Future work is intentionally separated into pragmatic utility improvements and
research that must prove itself elsewhere.

## Pragmatic utility direction

### Native GNU Findutils backend

Use topology-expanded filesystem roots as disjoint, drive-aware inputs to GNU
`find`, consuming NUL-delimited output and retaining `magik-search` aggregation,
privacy controls, statistics, and optional Magika post-classification.

Prioritize a read-only predicate surface:

- `-name`, `-iname`, `-path`, `-ipath`, `-regex`, `-iregex`;
- `-type`, `-size`, `-mtime`, `-mmin`, `-newer`, `-empty`;
- `-mindepth`, `-maxdepth`, and safe filesystem-boundary controls;
- `-print`, `-print0`, JSONL, and validated formatting modes.

Do not proxy destructive or command-execution actions such as `-delete`,
`-exec`, `-execdir`, `-ok`, or `-okdir` by default.

### Content-aware filtering

Use cheap native name/metadata predicates first. Invoke Magika only when the
user explicitly requests content type, MIME type, confidence, or
extension/content mismatch filtering.

## Explicitly separate research

Learned pause/resume HDD concurrency, state-conditioned calibration transport,
empirical subtree compatibility, FIEMAP-informed locality, and observer-effect
correction belong to the standalone `adaptive-seek-interference-scheduling`
research program. They should enter this utility only after repeatable evidence
shows an end-to-end benefit over serial and simple adaptive baselines.
