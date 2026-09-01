#!/usr/bin/env sh
set -eu

usage() {
  printf '%s\n' \
    'Usage: ./scripts/install.sh [--with-magika] [--force]' \
    '' \
    'Installs magik-search into an isolated user virtual environment and' \
    "links the command into ~/.local/bin (or \$XDG_BIN_HOME)."
}

with_magika=0
force=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --with-magika) with_magika=1 ;;
    --force) force=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'install.sh: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(dirname -- "$script_dir")
python_bin=${PYTHON:-python3}

if ! command -v "$python_bin" >/dev/null 2>&1; then
  printf 'install.sh: Python 3.10 or newer is required\n' >&2
  exit 1
fi
if ! "$python_bin" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
  printf 'install.sh: Python 3.10 or newer is required\n' >&2
  exit 1
fi

data_base=${XDG_DATA_HOME:-"$HOME/.local/share"}
bin_dir=${XDG_BIN_HOME:-"$HOME/.local/bin"}
install_root="$data_base/magik-search"
venv_dir="$install_root/venv"
command_path="$bin_dir/magik-search"

if [ -e "$command_path" ] || [ -L "$command_path" ]; then
  if [ "$force" -ne 1 ] && [ "$(readlink "$command_path" 2>/dev/null || true)" != "$venv_dir/bin/magik-search" ]; then
    printf 'install.sh: %s already exists; use --force to replace it\n' "$command_path" >&2
    exit 1
  fi
fi

mkdir -p "$install_root" "$bin_dir"
if [ ! -x "$venv_dir/bin/python" ]; then
  "$python_bin" -m venv "$venv_dir"
fi

if [ "$with_magika" -eq 1 ]; then
  "$venv_dir/bin/python" -m pip install --disable-pip-version-check "${repo_root}[magika]"
else
  "$venv_dir/bin/python" -m pip install --disable-pip-version-check "$repo_root"
fi
ln -sfn "$venv_dir/bin/magik-search" "$command_path"

printf 'Installed %s\n' "$("$command_path" --version)"
printf 'Command: %s\n' "$command_path"
case ":${PATH}:" in
  *":$bin_dir:"*) ;;
  *) printf 'Add %s to PATH to invoke magik-search directly.\n' "$bin_dir" ;;
esac
printf 'Next: magik-search doctor\n'
