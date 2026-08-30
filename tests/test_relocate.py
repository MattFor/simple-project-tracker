import io
import os
import tomllib

from pathlib import Path
from contextlib import redirect_stdout

from tests.helpers import make_settings

from tracker.cli.app import fuse, split
from tracker.cli.entries import Context
from tracker.cli.relocate import command_move


def isolate(tmp_path: Path) -> Path:
	"""Every file tracker knows about."""

	home = tmp_path / "home"
	home.mkdir(exist_ok=True)

	os.environ["XDG_CONFIG_HOME"] = str(tmp_path / "config")
	os.environ["XDG_DATA_HOME"] = str(tmp_path / "share")
	os.environ["XDG_STATE_HOME"] = str(tmp_path / "state")

	os.environ["TRACKER_SETTINGS"] = str(home / "settings.toml")
	os.environ["TRACKER_DATA"] = str(home / "data.pkl")
	os.environ["TRACKER_TODOS"] = str(home / "todos.pkl")
	os.environ["TRACKER_VIEW"] = str(home / "view.json")

	return home


def context(tmp_path: Path) -> Context:
	_ = isolate(tmp_path)

	return Context(settings=make_settings(), data={}, assume_yes=True)


def run(holder: Context, *args: str) -> str:
	stream = io.StringIO()

	with redirect_stdout(stream):
		_ = command_move(holder, list(args))

	return stream.getvalue()


def written(path: Path) -> dict[str, object]:
	return tomllib.loads(path.read_text(encoding="utf-8"))


def test_it_says_where_everything_lives(tmp_path: Path):
	holder = context(tmp_path)

	shown = run(holder)

	for name in ("settings", "database", "todos"):
		assert name in shown

	assert "TRACKER_DATA" in shown


def test_a_todo_list_moves_and_the_setting_follows(tmp_path: Path):
	home = isolate(tmp_path)
	holder = Context(settings=make_settings(), data={}, assume_yes=True)

	settings = home / "settings.toml"
	_ = settings.write_text("[display]\nlist_limit = 5\n", encoding="utf-8")

	todos = home / "todos.pkl"
	_ = todos.write_bytes(b"a todo list")
	_ = todos.with_name("todos.pkl.undo").write_bytes(b"the one before")

	sync = tmp_path / "sync"

	shown = run(holder, "todos", f"{sync}/")

	assert "moved" in shown
	assert not todos.exists()

	assert (sync / "todos.pkl").read_bytes() == b"a todo list"
	assert (sync / "todos.pkl.undo").read_bytes() == b"the one before"

	stored = written(settings)

	assert stored["todos"] == {"database": str(sync / "todos.pkl")}
	assert stored["display"] == {"list_limit": 5}


def test_a_home_path_is_stored_as_it_was_typed(tmp_path: Path):
	home = isolate(tmp_path)
	holder = Context(settings=make_settings(), data={}, assume_yes=True)

	settings = home / "settings.toml"
	_ = settings.write_text("[display]\n", encoding="utf-8")

	previous = os.environ.get("HOME")
	os.environ["HOME"] = str(tmp_path / "elsewhere")

	try:
		_ = run(holder, "database", "~/somewhere/data.pkl")
	finally:
		if previous is None:
			del os.environ["HOME"]
		else:
			os.environ["HOME"] = previous

	assert written(settings)["database"] == {"file": "~/somewhere/data.pkl"}


def test_a_file_already_there_is_kept_rather_than_overwritten(tmp_path: Path):
	home = isolate(tmp_path)
	holder = Context(settings=make_settings(), data={}, assume_yes=True)

	_ = (home / "settings.toml").write_text("[display]\n", encoding="utf-8")

	mine = home / "todos.pkl"
	_ = mine.write_bytes(b"mine")

	sync = tmp_path / "sync"
	sync.mkdir()

	theirs = sync / "todos.pkl"
	_ = theirs.write_bytes(b"already syncing")

	shown = run(holder, "todos", str(theirs))

	assert "keeping it" in shown
	assert theirs.read_bytes() == b"already syncing"
	assert mine.read_bytes() == b"mine"

	assert written(home / "settings.toml")["todos"] == {"database": str(theirs)}


def test_the_settings_leave_a_link_where_they_were_found(tmp_path: Path):
	home = isolate(tmp_path)

	settings = home / "settings.toml"
	_ = settings.write_text("[display]\nlist_limit = 5\n", encoding="utf-8")

	holder = Context(settings=make_settings(), data={}, assume_yes=True)

	sync = tmp_path / "sync"

	shown = run(holder, "settings", f"{sync}/")

	assert "moved" in shown
	assert not settings.exists()
	assert (sync / "settings.toml").read_text(encoding="utf-8").startswith("[display]")

	link = Path(os.environ["XDG_CONFIG_HOME"]) / "tracker" / "settings.toml"

	assert link.is_symlink()
	assert link.resolve() == (sync / "settings.toml").resolve()


def test_the_shipped_settings_are_copied_never_moved(tmp_path: Path):
	_ = isolate(tmp_path)

	from tracker.config import paths

	del os.environ["TRACKER_SETTINGS"]

	holder = Context(settings=make_settings(), data={}, assume_yes=True)

	shipped = paths.bundled_file(paths.SETTINGS_NAME)
	sync = tmp_path / "sync"

	shown = run(holder, "settings", f"{sync}/")

	assert "copied" in shown
	assert shipped.is_file()
	assert (sync / "settings.toml").read_text(encoding="utf-8")


def test_moving_somewhere_it_already_is_changes_nothing(tmp_path: Path):
	home = isolate(tmp_path)
	holder = Context(settings=make_settings(), data={}, assume_yes=True)

	_ = (home / "settings.toml").write_text("[display]\n", encoding="utf-8")

	shown = run(holder, "todos", str(home / "todos.pkl"))

	assert "already at" in shown
	assert "todos" not in written(home / "settings.toml")


def test_an_unknown_thing_to_move_is_refused(tmp_path: Path):
	holder = context(tmp_path)

	assert "unknown thing to move" in run(holder, "nonsense", "/tmp/whatever")


def test_the_command_line_knows_move():
	assert split(["move"]) == [("move", [])]
	assert split(["mv", "todos", "~/Sync"]) == [("move", ["todos", "~/Sync"])]

	assert fuse("mvt") == ("move", "t")
	assert fuse("mvs") == ("move", "s")

	assert split(["move", "todos", "~/check/list"]) == [
		("move", ["todos", "~/check/list"])
	]
