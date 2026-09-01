# Contributing

Thank you for improving magik-search. Keep changes Linux-focused, preserve the
metadata-only logging guarantee, and avoid introducing fixed drive or mount
names.

## Development setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
```

Before opening a pull request, exercise the public command surface:

```bash
magik-search --version
magik-search doctor
magik-search topology --json >/dev/null
magik-search scan tests --no-magika --no-tui -g '*.py'
```

Do not include event logs or summaries from real filesystems in issues or pull
requests: paths and metadata may be sensitive.
