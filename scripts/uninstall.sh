#!/usr/bin/env sh
set -eu

data_base=${XDG_DATA_HOME:-"$HOME/.local/share"}
bin_dir=${XDG_BIN_HOME:-"$HOME/.local/bin"}
install_root="$data_base/magik-search"
venv_dir="$install_root/venv"
command_path="$bin_dir/magik-search"

if [ -L "$command_path" ] && [ "$(readlink "$command_path")" = "$venv_dir/bin/magik-search" ]; then
  rm "$command_path"
  printf 'Removed %s\n' "$command_path"
elif [ -e "$command_path" ] || [ -L "$command_path" ]; then
  printf 'uninstall.sh: left unrelated command in place: %s\n' "$command_path" >&2
fi

if [ -d "$install_root" ]; then
  rm -rf -- "$install_root"
  printf 'Removed %s\n' "$install_root"
fi
printf 'magik-search uninstalled; scan output directories were preserved.\n'
