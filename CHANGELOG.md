# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.2] - 2026-09-01

### Fixed

- Expand nested mountpoints beneath requested roots into independent physical-drive lanes.
- Prevent parent traversal from duplicating mount trees already delegated to another lane.
- Match directory names as well as filenames while keeping directories metadata-only.

### Changed

- Show requested-root and expanded-mount counts in live and completed scan output.
- Reserve `--cross-filesystems` for boundaries not represented by discovered topology.

## [0.3.1] - 2026-09-01

### Fixed

- Propagate asynchronous event-log write failures instead of hanging during shutdown.
- Deduplicate repeated and safely overlapping scan roots.
- Include the final lifecycle event in summary event counts.
- Keep symlink candidates metadata-only when Magika classification is enabled.

### Changed

- Include community and operator documentation in source distributions.
- Check formatting and installer shell scripts in CI.

## [0.3.0] - 2026-08-12

### Added

- Physical-drive, mount, PV, and LV discovery through Linux storage CLIs.
- Adaptive per-drive traversal scouts and I/O/thermal throttling.
- Complete metadata JSONL telemetry and lifecycle statistics.
- Live colored filesystem tree and approximate per-drive progress.
- Optional batched Magika classification.
- `scan`, `topology`, `stats`, and `doctor` command surfaces.
- Isolated user installer, uninstaller, packaging metadata, and GitHub CI.
