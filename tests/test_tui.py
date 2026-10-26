from pathlib import Path

import pytest

from tests.helpers import SAMPLE, make_projects, make_settings
from tracker.core.models import Project
from tracker.core.todos import new_todo
from tracker.ui import mentions

from tracker.util.text import strip_ansi
from tracker.ui.tui import (
	ELSEWHERE,
	Browser,
	Node,
	Row,
	build_tree,
	cycle,
	flatten,
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


def test_a_todo_named_after_a_project_shows_that_project_under_it(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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
