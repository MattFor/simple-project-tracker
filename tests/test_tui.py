import curses
from pathlib import Path

import pytest

from tests.helpers import SAMPLE, make_projects, make_settings
from tracker.core.models import Project
from tracker.core.storage import load_data, save_data
from tracker.core.todos import load_todos, new_todo
from tracker.ui import mentions

from tracker.util.text import strip_ansi
from tracker.ui.tui import (
	ELSEWHERE,
	Browser,
	Node,
	Row,
	build_tree,
	cycle,
	edit_line,
	flatten,
	fold,
	mention_of,
	pick,
	pick_todos,
)

WHEN = "2026-01-01 10:00:00"


def tree(*entries: tuple[str, str]):
	projects = make_projects(*((path, status, WHEN, "") for path, status in entries))

	return build_tree(list(projects.items()), ["/work"])


def labels(rows: list[Row]) -> list[str]:
	return ["  " * depth + node.name for depth, node in rows]


def test_projects_hang_under_their_folders_and_strays_go_elsewhere():
	nodes = tree(
		("/work/projects/python/tracker", "dev"),
		("/work/projects/c++/hprint", "done"),
		("/work/personal/mood", "unknown"),
		("/tmp/scratch", "dev"),
	)

	assert labels(flatten(nodes, set())) == [
		"/work",
		"  personal",
		"    mood",
		"  projects",
		"    c++",
		"      hprint",
		"    python",
		"      tracker",
		ELSEWHERE,
		"  /tmp/scratch",
	]


def test_a_collapsed_folder_hides_its_projects_but_keeps_counting_them():
	nodes = tree(
		("/work/projects/python/tracker", "dev"),
		("/work/projects/c++/hprint", "done"),
	)

	rows = flatten(nodes, {"/work/projects"})

	assert labels(rows) == ["/work", "  projects"]
	assert rows[1][1].count() == 2


def test_a_project_holding_projects_is_a_folder_with_a_status():
	nodes = tree(("/work/abba", "dev"), ("/work/abba/lib/inicpp", "unknown"))

	abba = flatten(nodes, set())[1][1]

	assert abba.name == "abba"
	assert abba.project is not None and abba.project["status"] == "dev"
	assert abba.count() == 2


def names(items: list[tuple[str, Project]]) -> list[str]:
	return [path.rsplit("/", 1)[1] for path, _ in items]


def test_pick_hides_what_the_display_filter_hides_unless_asked_for_everything():
	projects = make_projects(*SAMPLE)
	settings = make_settings(display__filter=["-s:archived"])

	assert "beta" not in names(pick(projects, settings, sort="name"))
	assert names(pick(projects, settings, every=True, sort="name")) == [
		"alpha",
		"beta",
		"gamma",
	]


def test_pick_narrows_by_status_and_by_search_over_paths_and_notes():
	projects = make_projects(*SAMPLE)
	settings = make_settings()

	assert names(pick(projects, settings, status="todo")) == ["gamma"]
	assert names(pick(projects, settings, query="SHORT")) == ["alpha"]
	assert names(pick(projects, settings, query="gam")) == ["gamma"]


def test_pick_sorts_the_newest_first_when_sorting_by_last_touched():
	projects = make_projects(*SAMPLE)

	picked = pick(projects, make_settings(), sort="last_touched")

	assert names(picked) == ["beta", "alpha", "gamma"]


def test_pick_todos_narrows_by_status_and_search_and_follows_the_sort():
	todos = {
		"1": new_todo("tracker", status="todo", note="the tui @tracker", todo_id=1),
		"2": new_todo("lexiglance", status="done", note="respond to the PR", todo_id=2),
	}
	settings = make_settings()

	assert [key for key, _ in pick_todos(todos, settings)] == ["1", "2"]
	assert [key for key, _ in pick_todos(todos, settings, sort="name")] == ["2", "1"]
	assert [key for key, _ in pick_todos(todos, settings, status="done")] == ["2"]
	assert [key for key, _ in pick_todos(todos, settings, query="TUI")] == ["1"]


def test_a_todo_named_after_a_project_shows_that_project_under_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv("TRACKER_TODOS", str(tmp_path / "todos.pkl"))
	projects = make_projects(*SAMPLE)
	mentions.use(projects)
	browser = Browser(projects, make_settings())

	def shown(name: str) -> str:
		todo = new_todo(name, status="todo", note="ship it", todo_id=1)

		return strip_ansi("\n".join(browser.describe(Node(name, "1", todo=todo))))

	assert "short note" in shown("alpha")
	assert "short note" not in shown("alp")


def test_cycle_walks_the_options_and_back_to_none():
	assert cycle(["a", "b"], None) == "a"
	assert cycle(["a", "b"], "a") == "b"
	assert cycle(["a", "b"], "b") is None
	assert cycle(["a", "b"], "gone") is None


def test_edit_line_types_moves_and_deletes_around_the_cursor():
	assert edit_line("helo", 3, ord("l")) == ("hello", 4)
	assert edit_line("hello", 5, 127) == ("hell", 4)
	assert edit_line("hello", 0, 127) == ("hello", 0)
	assert edit_line("hello there", 11, 23) == ("hello ", 6)
	assert edit_line("hello there", 6, 21) == ("there", 0)


def test_fold_wraps_a_field_under_its_value_and_breaks_a_long_word():
	def text(line: str, width: int) -> list[str]:
		return ["".join(part for part, _ in row) for row in fold(line, width)]

	assert text("  Note    short", 40) == ["  Note    short"]
	assert text("  Last commit   abc123 the subject of it", 34) == [
		"  Last commit   abc123 the subject",
		"                of it",
	]
	assert text("  Path   /a/very/long/path", 20) == ["  Path   /a/very/lon", "         g/path"]
	assert text("\x1b[1mbold words here\x1b[0m", 10) == ["bold words", "here"]


def test_mention_of_names_the_project_so_it_finds_its_way_back():
	projects = make_projects(*SAMPLE, ("/elsewhere/alpha", "dev", WHEN, ""), ("/x/two words", "dev", WHEN, ""))

	assert mention_of("/home/user/code/beta", projects) == "@beta"
	assert mention_of("/x/two words", projects) == "@(two words)"
	assert mention_of("/elsewhere/alpha", projects) == "@4"


def press(browser: Browser, *keys: str | int) -> None:
	for key in keys:
		for code in [key] if isinstance(key, int) else map(ord, key):
			assert browser.handle(code)


def test_the_browser_adds_edits_links_and_removes_todos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setenv("TRACKER_TODOS", str(tmp_path / "todos.pkl"))
	monkeypatch.setenv("TRACKER_DATA", str(tmp_path / "data.pkl"))
	settings = make_settings()
	assert save_data(make_projects(*SAMPLE), settings)
	projects = load_data(settings)
	mentions.use(projects)
	browser = Browser(projects, settings)

	def select(path: str) -> None:
		browser.move([node.path for _, node in browser.rows].index(path))

	def at() -> str:
		node = browser.selected()

		return node.path if node else ""

	select("/home/user/code/alpha")
	press(browser, "n", "ship it", 10)
	todo = load_todos(settings)["1"]
	assert (todo["name"], todo["status"], todo.get("note")) == ("ship it", "todo", "@alpha")

	press(browser, "p", 21, "paused", 10)
	assert load_data(settings)["/home/user/code/alpha"]["status"] == "paused"

	press(browser, "o")
	assert browser.todo_mode and at() == "1"

	press(browser, "x")
	assert load_todos(settings)["1"]["status"] == "done"
	assert "done_at" in load_todos(settings)["1"]

	press(browser, "m", 23, "it", 10, "i", " soon", 10)
	assert (load_todos(settings)["1"]["name"], load_todos(settings)["1"].get("note")) == ("ship it", "@alpha soon")

	press(browser, "\t")
	select("/home/user/code/gamma")
	press(browser, "@")
	assert browser.todo_mode and browser.linking is not None
	press(browser, "@")
	assert load_todos(settings)["1"].get("note") == "@alpha soon @gamma"
	assert browser.linking is None

	press(browser, "o")
	assert not browser.todo_mode and at() == "/home/user/code/alpha"

	press(browser, "\t", curses.KEY_DC)
	assert load_todos(settings) == {}

	press(browser, "u")
	assert "1" in load_todos(settings)
