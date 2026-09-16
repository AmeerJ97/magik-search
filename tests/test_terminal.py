import io

from magik_search.terminal import wordmark


class TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_wordmark_is_interactive_only(monkeypatch) -> None:
    assert wordmark(io.StringIO()) == ""
    tty = TtyBuffer()
    assert "magik-search" in wordmark(tty)
    monkeypatch.setenv("NO_COLOR", "1")
    assert "\033[" not in wordmark(tty)
