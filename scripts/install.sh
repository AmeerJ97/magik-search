#!/usr/bin/env sh
set -eu

usage() {
  printf '%s\n' \
    'Usage: ./scripts/install.sh [--without-magika] [--force]' \
    '' \
    'Installs magik-search into an isolated user virtual environment and' \
    "links the command into ~/.local/bin (or \$XDG_BIN_HOME)." \
    '' \
    'Magika content verification is installed by default.' \
    'Use --without-magika for metadata-only operation.' \
    'The legacy --with-magika option is still accepted.'
}

with_magika=1
force=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --with-magika) with_magika=1 ;;
    --without-magika) with_magika=0 ;;
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

if [ -t 1 ]; then
  printf '\n      ✦\n  ◇━━╯  magik-search installer\n\n'
else
  printf 'magik-search installer\n'
fi

if [ -e "$command_path" ] || [ -L "$command_path" ]; then
  if [ "$force" -ne 1 ] && [ "$(readlink "$command_path" 2>/dev/null || true)" != "$venv_dir/bin/magik-search" ]; then
    printf 'install.sh: %s already exists; use --force to replace it\n' "$command_path" >&2
    exit 1
  fi
fi

printf '[1/5] Python      %s\n' "$("$python_bin" -c 'import sys; print(sys.version.split()[0])')"
mkdir -p "$install_root" "$bin_dir"
if [ ! -x "$venv_dir/bin/python" ]; then
  printf '[2/5] Environment creating isolated virtual environment\n'
  if ! "$python_bin" -m venv "$venv_dir"; then
    printf '%s\n' \
      'install.sh: could not create a virtual environment.' \
      'On Debian/Ubuntu, install python3-venv and try again:' \
      '  sudo apt-get install python3-venv' >&2
    exit 1
  fi
else
  printf '[2/5] Environment reusing %s\n' "$venv_dir"
fi
if [ ! -x "$venv_dir/bin/python" ] || ! "$venv_dir/bin/python" -m pip --version >/dev/null 2>&1; then
  printf 'install.sh: pip is unavailable in %s\n' "$venv_dir" >&2
  exit 1
fi

if [ "$with_magika" -eq 1 ]; then
  printf '[3/5] Packages    upgrading magik-search + Magika\n'
  "$venv_dir/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade "${repo_root}[magika]"
else
  printf '[3/5] Packages    upgrading magik-search (metadata-only)\n'
  if "$venv_dir/bin/python" -c 'import magika' >/dev/null 2>&1; then
    "$venv_dir/bin/python" -m pip uninstall --quiet --yes magika
  fi
  "$venv_dir/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade "$repo_root"
fi
ln -sfn "$venv_dir/bin/magik-search" "$command_path"

printf '[4/5] Command     %s\n' "$command_path"
version=$("$command_path" --version)
if [ "$with_magika" -eq 1 ] && ! "$venv_dir/bin/python" -c 'import magika' >/dev/null 2>&1; then
  printf '%s\n' \
    'install.sh: Magika was requested but could not be initialized.' \
    "Retry directly with: $venv_dir/bin/python -m pip install --upgrade magika" >&2
  exit 1
fi

printf '[5/5] Verified    %s\n' "$version"
case ":${PATH}:" in
  *":$bin_dir:"*) ;;
  *)
    printf '\nAdd the command directory to PATH:\n'
    printf '  export PATH="%s:%s"\n' "$bin_dir" "\$PATH"
    ;;
esac

printf '\nInstallation complete. System check:\n\n'
"$command_path" doctor
