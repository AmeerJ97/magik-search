#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for magik-search.
#
# Installs the project (editable) together with the dev tooling (pytest, ruff,
# build) and the optional Magika classifier into the system interpreter. This
# keeps the documented commands (magik-search, pytest, ruff) and every Makefile
# target working against the default `python3` with no shell-profile changes.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

# util-linux (lsblk/findmnt) ships with the base image. python3-venv provides
# ensurepip so `python -m build` (the Makefile `build` target) can create the
# isolated build environments it needs.
if ! dpkg -s python3-venv >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv
fi

# --break-system-packages is required because python3-venv marks the interpreter
# as externally managed (PEP 668). Installing into the default interpreter is
# safe on the disposable Cloud Agent VM and is what makes `python3 -m ...` and
# the Makefile targets work without PATH or profile tweaks.
sudo pip3 install --break-system-packages --disable-pip-version-check -e '.[dev,magika]'

magik-search --version
