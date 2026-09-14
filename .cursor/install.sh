#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for magik-search.
#
# Installs the project (editable) together with the dev tooling (pytest, ruff,
# build) and the optional Magika classifier into the invoking user's site. This
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

# Install into the current user's site (NOT root). Installing editable as root
# would create a root-owned magik_search.egg-info in the repo and break
# `python -m build`/tests for the agent user. --break-system-packages is
# required under PEP 668 because python3-venv marks the interpreter externally
# managed; the user site keeps this scoped to the agent user.
python3 -m pip install --user --break-system-packages --disable-pip-version-check -e '.[dev,magika]'

# pip --user drops console scripts in the user base bin, which is not on PATH.
# Symlink the documented commands into /usr/local/bin (already on PATH) so they
# work without editing any shell profile.
user_bin="$(python3 -m site --user-base)/bin"
for exe in magik-search pytest ruff; do
  sudo ln -sfn "$user_bin/$exe" "/usr/local/bin/$exe"
done

magik-search --version
