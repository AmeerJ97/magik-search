from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import TextIO

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"


def supports_color(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    return bool(
        getattr(stream, "isatty", lambda: False)()
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM", "") != "dumb"
    )


def supports_unicode(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        "◆✓→".encode(encoding)
    except UnicodeEncodeError:
        return False
    return True


def terminal_width(stream: TextIO | None = None, default: int = 88) -> int:
    stream = stream or sys.stdout
    if not getattr(stream, "isatty", lambda: False)():
        return default
    return max(50, shutil.get_terminal_size((default, 24)).columns)


@dataclass(frozen=True)
class Theme:
    stream: TextIO = field(default_factory=lambda: sys.stdout)

    @property
    def color(self) -> bool:
        return supports_color(self.stream)

    @property
    def unicode(self) -> bool:
        return supports_unicode(self.stream)

    def paint(self, text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if self.color else text

    def symbol(self, unicode_value: str, plain_value: str) -> str:
        return unicode_value if self.unicode else plain_value

    def heading(self, text: str) -> str:
        marker = self.symbol("◆", ">")
        return self.paint(f"{marker} {text}", BOLD + CYAN)

    def status(self, state: str) -> str:
        symbols = {
            "ok": ("✓", "OK", GREEN),
            "warning": ("!", "!", YELLOW),
            "error": ("✗", "X", RED),
            "off": ("○", "-", DIM),
        }
        symbol, plain, color = symbols[state]
        return self.paint(self.symbol(symbol, plain), color)


def wordmark(stream: TextIO | None = None) -> str:
    stream = stream or sys.stdout
    theme = Theme(stream)
    if not getattr(stream, "isatty", lambda: False)():
        return ""
    sparkle = theme.symbol("✦", "*")
    wand = theme.symbol("◇━━╯", "o--/")
    lines = [
        f"      {theme.paint(sparkle, MAGENTA)}",
        f"  {theme.paint(wand, CYAN)}  {theme.paint('magik-search', BOLD)}",
        f"         {theme.paint('drive-aware discovery for Linux', DIM)}",
    ]
    return "\n".join(lines)


def bar(value: float, width: int = 18, stream: TextIO | None = None) -> str:
    stream = stream or sys.stdout
    theme = Theme(stream)
    filled = min(width, max(0, round(value * width)))
    full, empty = ("━", "─") if theme.unicode else ("#", "-")
    return f"{theme.paint(full * filled, GREEN)}{theme.paint(empty * (width - filled), DIM)}"


def format_percent(value: float) -> str:
    percent = value * 100
    if 0 < percent < 0.01:
        return "<0.01%"
    return f"{percent:.1f}%" if percent < 10 else f"{percent:.0f}%"


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(size) < 1024 or unit == "PiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"
