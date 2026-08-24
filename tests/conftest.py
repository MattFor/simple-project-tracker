import os
import sys
import tempfile

from pathlib import Path
from collections.abc import Iterator

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracker.ui import ansi


@pytest.fixture(autouse=True)
def isolated_view(tmp_path: Path) -> Iterator[None]:
	previous = os.environ.get("TRACKER_VIEW")

	os.environ["TRACKER_VIEW"] = str(tmp_path / "view.json")

	yield

	if previous is None:
		del os.environ["TRACKER_VIEW"]
	else:
		os.environ["TRACKER_VIEW"] = previous


@pytest.fixture(autouse=True)
def plain_output() -> Iterator[None]:
	ansi.C.set_enabled(False)

	yield

	ansi.C.set_enabled(False)


_ = os.environ.setdefault(
	"TRACKER_VIEW", os.path.join(os.path.realpath(tempfile.mkdtemp()), "view.json")
)
