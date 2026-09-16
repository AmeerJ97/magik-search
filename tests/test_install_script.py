import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]


def _fake_python(path: Path) -> None:
    path.write_text(
        """#!/bin/sh
if [ "$1" = "-c" ]; then
  case "$2" in
    *"print(sys.version"*) printf '3.12.0\\n' ;;
  esac
  exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  cp "$0" "$3/bin/python"
  cat > "$3/bin/magik-search" <<'EOF'
#!/bin/sh
case "$1" in
  --version) printf 'magik-search 0.4.0\\n' ;;
  doctor) printf 'system check ok\\n' ;;
esac
EOF
  chmod +x "$3/bin/python" "$3/bin/magik-search"
  exit 0
fi
printf '%s\\n' "$*" >> "$FAKE_PYTHON_LOG"
exit 0
"""
    )
    path.chmod(0o755)


def _run_installer(tmp_path: Path, *arguments: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    fake_python = tmp_path / "python3"
    log = tmp_path / "python.log"
    _fake_python(fake_python)
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_BIN_HOME": str(tmp_path / "bin"),
        "PYTHON": str(fake_python),
        "FAKE_PYTHON_LOG": str(log),
        "PATH": os.environ["PATH"],
    }
    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "install.sh"), *arguments],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, log


def test_installer_includes_magika_and_upgrade_by_default(tmp_path: Path) -> None:
    result, log = _run_installer(tmp_path)
    assert result.returncode == 0, result.stderr
    pip_call = log.read_text()
    assert "--upgrade" in pip_call
    assert f"{REPO_ROOT}[magika]" in pip_call
    assert (tmp_path / "bin" / "magik-search").is_symlink()
    assert "Installation complete" in result.stdout

    rerun, _ = _run_installer(tmp_path)
    assert rerun.returncode == 0, rerun.stderr
    assert "reusing" in rerun.stdout


def test_installer_supports_explicit_metadata_only_mode(tmp_path: Path) -> None:
    result, log = _run_installer(tmp_path, "--without-magika")
    assert result.returncode == 0, result.stderr
    pip_call = log.read_text()
    assert f"{REPO_ROOT}[magika]" not in pip_call
    assert f"--upgrade {REPO_ROOT}" in pip_call
    assert "pip uninstall --quiet --yes magika" in pip_call
