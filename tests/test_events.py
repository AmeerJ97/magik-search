from pathlib import Path

import pytest

from magik_search.events import EventStream


@pytest.mark.skipif(not Path("/dev/full").exists(), reason="Linux full-device fixture is unavailable")
def test_event_writer_reports_storage_failure() -> None:
    events = EventStream(Path("/dev/full"), "storage-failure")
    events.emit("probe")

    with pytest.raises(OSError, match="event writer failed"):
        events.close()
