import io
import os

from pathlib import Path
from contextlib import redirect_stdout

from tests.helpers import SAMPLE, make_projects, make_settings

from tracker.core.storage import load_data, save_data
from tracker.core.undo import backup_path, differences, restore
from tracker.cli.commands import Context, command_undo, marks_used


def isolate(tmp_path: Path) -> None:
	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")
	os.environ["TRACKER_VIEW"] = str(tmp_path / "view.json")


def test_the_first_change_can_be_taken_back(tmp_path: Path):
	isolate(tmp_path)

	settings = make_settings()
	projects = make_projects(*SAMPLE)

	assert save_data(projects, settings, undoable=True)

	projects["/home/user/code/alpha"]["status"] = "archived"

	assert save_data(projects, settings, undoable=True)

	swapped = restore(settings)

	assert swapped is not None
	assert load_data(settings)["/home/user/code/alpha"]["status"] == "current"


def test_undoing_twice_puts_it_back(tmp_path: Path):
	isolate(tmp_path)

	settings = make_settings()
	projects = make_projects(*SAMPLE)

	_ = save_data(projects, settings, undoable=True)

	del projects["/home/user/code/beta"]

	_ = save_data(projects, settings, undoable=True)

	assert restore(settings) is not None
	assert "/home/user/code/beta" in load_data(settings)

	assert restore(settings) is not None
	assert "/home/user/code/beta" not in load_data(settings)


def test_a_save_that_is_not_a_change_keeps_the_undo(tmp_path: Path):
	isolate(tmp_path)

	settings = make_settings()
	projects = make_projects(*SAMPLE)

	_ = save_data(projects, settings, undoable=True)

	projects["/home/user/code/alpha"]["status"] = "archived"

	_ = save_data(projects, settings, undoable=True)

	# A lookup stamps last_used and saves must not consume the undo
	projects["/home/user/code/gamma"]["last_used"] = "2026-08-24 10:00:00"

	_ = save_data(projects, settings)

	assert restore(settings) is not None
	assert load_data(settings)["/home/user/code/alpha"]["status"] == "current"


def test_nothing_to_undo_is_not_a_crash(tmp_path: Path):
	isolate(tmp_path)

	settings = make_settings()

	assert not backup_path(settings).is_file()
	assert restore(settings) is None

	context = Context(settings=settings, data={})

	stream = io.StringIO()

	with redirect_stdout(stream):
		status = command_undo(context, [])

	assert status == 1
	assert "nothing to undo" in stream.getvalue()


def test_a_damaged_backup_is_refused(tmp_path: Path):
	isolate(tmp_path)

	settings = make_settings()

	_ = save_data(make_projects(*SAMPLE), settings, undoable=True)
	_ = backup_path(settings).write_bytes(b"this is not a pickle")

	assert restore(settings) is None
	assert len(load_data(settings)) == len(SAMPLE)


def test_the_summary_counts_what_moved():
	before = make_projects(*SAMPLE)
	after = make_projects(*SAMPLE)

	del after["/home/user/code/beta"]

	after["/home/user/code/delta"] = after["/home/user/code/alpha"].copy()
	after["/home/user/code/gamma"]["status"] = "blocked"

	assert differences(before, after) == (1, 1, 1)


def test_a_lookup_never_consumes_the_undo(tmp_path: Path):
	isolate(tmp_path)

	settings = make_settings()
	projects = make_projects(*SAMPLE)

	_ = save_data(projects, settings, undoable=True)

	context = Context(settings=settings, data=projects)

	@marks_used
	def handler(inner: Context, args: list[str]) -> int:
		del args

		_ = inner.select(["alpha"])

		return 0

	kept = backup_path(settings).read_bytes()

	assert handler(context, []) == 0
	assert backup_path(settings).read_bytes() == kept
