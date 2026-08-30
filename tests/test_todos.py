import io
import os

from pathlib import Path
from contextlib import redirect_stdout

from tests.helpers import make_settings

from tracker.cli.app import fuse, split
from tracker.cli.entries import Context
from tracker.cli.todo import command_todo

from tracker.core.todos import (
	load_todos,
	new_todo,
	normalise,
	resolve_selection,
	save_todos,
	sort_todos,
	status_of,
)


def isolate(tmp_path: Path) -> None:
	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")
	os.environ["TRACKER_TODOS"] = str(tmp_path / "todos.pkl")
	os.environ["TRACKER_VIEW"] = str(tmp_path / "view.json")


def context(tmp_path: Path, **overrides: object) -> Context:
	isolate(tmp_path)

	return Context(settings=make_settings(**overrides), data={}, assume_yes=True)


def run(holder: Context, *args: str) -> str:
	stream = io.StringIO()

	with redirect_stdout(stream):
		_ = command_todo(holder, list(args))

	return stream.getvalue()


def names(holder: Context) -> list[str]:
	todos = load_todos(holder.settings)

	return [todo["name"] for _, todo in sort_todos(todos, holder.settings)]


#
# The list
#


def test_a_todo_is_added_and_read_back(tmp_path: Path):
	holder = context(tmp_path)

	assert "no todos yet" in run(holder, "list")

	_ = run(holder, "add", "write", "the", "changelog")

	todos = load_todos(holder.settings)

	assert len(todos) == 1

	todo = todos["1"]

	assert todo["name"] == "write the changelog"
	assert todo["status"] == "todo"
	assert todo.get("created") == todo.get("updated")


def test_every_todo_keeps_its_own_id(tmp_path: Path):
	holder = context(tmp_path)

	for name in ("first", "second", "third"):
		_ = run(holder, "add", name)

	_ = run(holder, "remove", "2")
	_ = run(holder, "add", "fourth")

	todos = load_todos(holder.settings)

	assert sorted(todos) == ["1", "3", "4"]
	assert todos["4"]["name"] == "fourth"


def test_the_list_can_be_searched_and_filtered(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "write the changelog")
	_ = run(holder, "add", "fix the daemon")
	_ = run(holder, "done", "2")

	assert "daemon" in run(holder, "list", "daemon")
	assert "changelog" not in run(holder, "list", "daemon")

	shown = run(holder, "list", "s:done")

	assert "daemon" in shown
	assert "changelog" not in shown


def test_a_status_can_be_kept_out_of_the_listing(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "write the changelog")
	_ = run(holder, "add", "fix the daemon")
	_ = run(holder, "done", "2")

	shown = run(holder, "list", "!s:done")

	assert "changelog" in shown
	assert "daemon" not in shown


#
# Editing
#


def test_done_marks_it_and_reopen_puts_it_back(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "read the manual")
	_ = run(holder, "done", "1")

	todo = load_todos(holder.settings)["1"]

	assert status_of(todo) == "done"
	assert todo.get("done_at")

	_ = run(holder, "reopen", "1")

	todo = load_todos(holder.settings)["1"]

	assert status_of(todo) == "todo"
	assert "done_at" not in todo


def test_a_todo_may_come_before_its_action(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "read the manual")

	_ = run(holder, "1", "done")

	assert status_of(load_todos(holder.settings)["1"]) == "done"

	_ = run(holder, "1", "st", "blocked")

	assert status_of(load_todos(holder.settings)["1"]) == "blocked"


def test_a_bare_note_clears_it(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "read the manual")
	_ = run(holder, "note", "1", "later", "this", "week")

	assert load_todos(holder.settings)["1"].get("note") == "later this week"

	_ = run(holder, "note", "1")

	assert load_todos(holder.settings)["1"].get("note") == ""


def test_renaming_keeps_everything_else(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "read the manual")
	_ = run(holder, "note", "1", "on the train")
	_ = run(holder, "rename", "1", "read the manual twice")

	todo = load_todos(holder.settings)["1"]

	assert todo["name"] == "read the manual twice"
	assert todo.get("note") == "on the train"
	assert todo["id"] == 1


def test_a_range_edits_every_todo_in_it(tmp_path: Path):
	holder = context(tmp_path)

	for name in ("first", "second", "third"):
		_ = run(holder, "add", name)

	_ = run(holder, "2-3", "st", "blocked")

	todos = load_todos(holder.settings)

	assert [status_of(todos[key]) for key in ("1", "2", "3")] == [
		"todo",
		"blocked",
		"blocked",
	]


def test_editing_nothing_changes_nothing(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "read the manual")

	assert "nothing changed" in run(holder, "1", "st", "todo")


#
# Removing
#


def test_removing_needs_every_selector_to_resolve(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "read the manual")

	shown = run(holder, "remove", "1", "nonsense")

	assert "did nothing" in shown
	assert load_todos(holder.settings)


def test_clear_drops_only_the_finished_ones(tmp_path: Path):
	holder = context(tmp_path)

	for name in ("first", "second", "third"):
		_ = run(holder, "add", name)

	_ = run(holder, "done", "1-2")
	_ = run(holder, "clear")

	assert names(holder) == ["third"]


#
# Storage
#


def test_undo_takes_back_the_last_change(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "read the manual")
	_ = run(holder, "add", "write the changelog")
	_ = run(holder, "remove", "2")

	assert names(holder) == ["read the manual"]

	_ = run(holder, "undo")

	assert names(holder) == ["read the manual", "write the changelog"]

	_ = run(holder, "undo")

	assert names(holder) == ["read the manual"]


def test_a_broken_entry_is_repaired():
	broken = {
		"1": {"name": "kept", "status": "todo"},
		"oops": {"name": "", "status": ""},
		"3": "not a todo",
	}

	repaired = normalise(broken)

	assert len(repaired) == 2
	assert repaired["1"]["name"] == "kept"

	rebuilt = next(todo for key, todo in repaired.items() if key != "1")

	assert rebuilt["name"].startswith("todo ")
	assert rebuilt["status"] == "unknown"


def test_the_order_follows_the_setting(tmp_path: Path):
	isolate(tmp_path)

	settings = make_settings(todos__sort="name")

	todos = {
		str(index): new_todo(name, status="todo", todo_id=index)
		for index, name in enumerate(("gamma", "alpha", "beta"), 1)
	}

	assert [todo["name"] for _, todo in sort_todos(todos, settings)] == [
		"alpha",
		"beta",
		"gamma",
	]

	backwards = settings.override("todos.newest_first", True)

	assert [todo["name"] for _, todo in sort_todos(todos, backwards)] == [
		"gamma",
		"beta",
		"alpha",
	]


def test_the_todo_list_is_kept_apart_from_the_projects(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "read the manual")

	assert (tmp_path / "todos.pkl").is_file()
	assert not (tmp_path / "data.pkl").exists()


#
# Selection
#


def test_a_todo_is_found_by_number_name_or_status(tmp_path: Path):
	isolate(tmp_path)

	settings = make_settings()

	todos = {
		"1": new_todo("write the changelog", status="todo", todo_id=1),
		"2": new_todo("fix the daemon", status="blocked", todo_id=2),
	}

	assert save_todos(todos, settings, undoable=False)

	for selector in ("1", "#1", "i:1", "changelog", "write the changelog"):
		selected, unmatched = resolve_selection(todos, settings, [selector], quiet=True)

		assert not unmatched, selector
		assert list(selected) == ["1"], selector

	selected, _ = resolve_selection(todos, settings, ["s:blocked"], quiet=True)

	assert list(selected) == ["2"]

	selected, _ = resolve_selection(todos, settings, ["all"], quiet=True)

	assert len(selected) == 2

	_, unmatched = resolve_selection(todos, settings, ["nothing"], quiet=True)

	assert unmatched == ["nothing"]


def test_a_temporary_id_points_at_the_last_listing(tmp_path: Path):
	holder = context(tmp_path, todos__sort="name")

	for name in ("gamma", "alpha", "beta"):
		_ = run(holder, "add", name)

	# alpha, beta, gamma on screen, so :1 is alpha and #1 is gamma
	_ = run(holder, "list")

	_ = run(holder, ":1", "st", "blocked")

	todos = load_todos(holder.settings)

	assert status_of(todos["2"]) == "blocked"
	assert status_of(todos["1"]) == "todo"

	_ = run(holder, "#1", "st", "shelf")

	assert status_of(load_todos(holder.settings)["1"]) == "shelf"


def test_the_two_numberings_do_not_disturb_each_other(tmp_path: Path):
	from tests.helpers import SAMPLE, make_projects

	from tracker.core.selection import temporary_ids as project_ids
	from tracker.core.todos import temporary_ids as todo_ids

	holder = context(tmp_path)
	holder.data = make_projects(*SAMPLE)

	from tracker.core.selection import pin_projects

	pinned = pin_projects(holder.data, holder.settings)

	_ = run(holder, "add", "read the manual")
	_ = run(holder, "list")

	assert project_ids(holder.data, holder.settings) == pinned
	assert todo_ids(load_todos(holder.settings), holder.settings) == {"1": 1}


#
# Display
#


def test_the_listing_does_not_count_itself(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "read the manual")

	shown = run(holder, "list")

	assert "read the manual" in shown
	assert "1 left" not in shown

	# The counts are what stats is for
	assert "1 left" in run(holder, "stats")


def test_the_counts_stay_grey_to_the_last_bracket(tmp_path: Path):
	from tracker.ui import ansi
	from tracker.ui.todos import summary

	isolate(tmp_path)

	todos = {"1": new_todo("read the manual", status="todo", todo_id=1)}

	ansi.C.set_enabled(True)

	try:
		line = summary(todos, make_settings())
	finally:
		ansi.C.set_enabled(False)

	assert line.endswith("\033[90m)\033[0m")


def test_the_todo_table_takes_its_own_columns(tmp_path: Path):
	holder = context(
		tmp_path,
		display__show_headers=True,
		display__columns=["tid", "name", "status", "last_touched"],
		todos__display__columns=["id", "name", "done_at"],
	)

	_ = run(holder, "add", "read the manual")

	shown = run(holder, "list")

	assert "DONE" in shown
	assert "TID" not in shown


def test_a_shared_column_still_reaches_the_todos(tmp_path: Path):
	holder = context(
		tmp_path,
		display__show_headers=True,
		display__columns=["tid", "name", "last_touched"],
	)

	_ = run(holder, "add", "read the manual")

	shown = run(holder, "list")

	# last_touched is the created a todo has instead
	assert "CREATED" in shown
	assert "STATUS" not in shown


def test_the_status_every_todo_starts_with_is_not_printed(tmp_path: Path):
	holder = context(tmp_path, display__show_headers=True)

	_ = run(holder, "add", "read the manual")

	shown = run(holder, "list")

	assert "read the manual" in shown

	# Nothing to say, so neither the cell nor the column is there
	assert "todo" not in shown
	assert "STATUS" not in shown


def test_a_status_of_its_own_brings_the_column_back(tmp_path: Path):
	holder = context(tmp_path, display__show_headers=True)

	_ = run(holder, "add", "read the manual")
	_ = run(holder, "add", "fix the daemon")
	_ = run(holder, "2", "st", "blocked")

	shown = run(holder, "list")

	assert "STATUS" in shown
	assert "blocked" in shown

	# The one still open leaves its cell empty
	assert "todo" not in shown


def test_the_status_left_out_is_the_one_new_todos_get(tmp_path: Path):
	holder = context(tmp_path, todos__new_status="open")

	_ = run(holder, "add", "read the manual")

	assert "open" not in run(holder, "list")

	_ = run(holder, "1", "st", "todo")

	assert "todo" in run(holder, "list")


def test_an_empty_last_column_takes_its_separator_with_it(tmp_path: Path):
	holder = context(
		tmp_path,
		display__vertical_separator=" | ",
		todos__display__show_headers=False,
		todos__display__columns=["tid", "name", "status"],
	)

	_ = run(holder, "add", "read the manual")
	_ = run(holder, "add", "fix the daemon")
	_ = run(holder, "2", "st", "blocked")

	rows = [line for line in run(holder, "list").splitlines() if line]

	assert rows[0].endswith("read the manual")
	assert rows[1].endswith("blocked")


def test_a_todo_row_format_is_its_own(tmp_path: Path):
	holder = context(tmp_path, todos__display__format="$>tid. $name")

	_ = run(holder, "add", "read the manual")

	assert "1. read the manual" in run(holder, "list")


def test_a_project_row_format_is_not_forced_onto_the_todos(tmp_path: Path):
	holder = context(tmp_path, display__format="$name $path")

	_ = run(holder, "add", "read the manual")

	shown = run(holder, "list")

	assert "read the manual" in shown
	assert "$path" not in shown


#
# The command line
#


def test_the_command_line_knows_the_todo_command():
	assert split(["td"]) == [("todo", [])]
	assert split(["todo"]) == [("todo", [])]
	assert split(["todos"]) == [("todo", [])]

	assert split(["td", "add", "fix the list"]) == [("todo", ["add", "fix the list"])]


def test_a_todo_swallows_the_words_of_other_commands():
	assert split(["td", "add", "check", "the", "list"]) == [
		("todo", ["add", "check", "the", "list"])
	]

	assert split(["td", "3", "note", "remove", "it", "later"]) == [
		("todo", ["3", "note", "remove", "it", "later"])
	]


def test_the_todo_actions_fuse_onto_the_command():
	assert fuse("tda") == ("todo", "a")
	assert fuse("tdl") == ("todo", "l")
	assert fuse("tdd") == ("todo", "d")
	assert fuse("tdc") == ("todo", "c")
	assert fuse("todostatus") == ("todo", "status")

	assert split(["tda", "read the manual"]) == [("todo", ["a", "read the manual"])]
	assert split(["tdd", "3"]) == [("todo", ["d", "3"])]


def test_a_bare_help_reaches_the_todo_section():
	assert split(["td", "help"]) == [("help", ["todo"])]
	assert split(["help", "todo"]) == [("help", ["todo"])]


#
# Mentions
#


def mentioned(text: str, **overrides: object) -> str:
	from tracker.ui import mentions

	from tests.helpers import SAMPLE, make_projects

	mentions.use(make_projects(*SAMPLE))

	try:
		return mentions.render(text, make_settings(**overrides))
	finally:
		mentions.forget()


def test_a_mention_becomes_the_project_it_names(tmp_path: Path):
	isolate(tmp_path)

	# beta was touched last, so it holds the first row
	assert mentioned("blocked by @alpha today") == "blocked by alpha#1:2 today"
	assert mentioned("see @(alpha)") == "see alpha#1:2"
	assert mentioned("see @2") == "see beta#2:1"


def test_a_mention_that_names_nothing_is_left_as_written(tmp_path: Path):
	isolate(tmp_path)

	for text in ("@nothing", "@", "mattfor@example.com", "@999"):
		assert mentioned(text) == text


def test_a_mention_wears_the_status_colour(tmp_path: Path):
	from tracker.ui import ansi

	isolate(tmp_path)

	ansi.C.set_enabled(True)

	try:
		shown = mentioned("@alpha")
	finally:
		ansi.C.set_enabled(False)

	assert "alpha#1:2" in shown
	assert shown.startswith("\033[32m")


def test_a_todo_note_shows_what_it_mentions(tmp_path: Path):
	from tracker.ui import mentions

	from tests.helpers import SAMPLE, make_projects

	holder = context(tmp_path)
	holder.data = make_projects(*SAMPLE)

	# What the command line hands over before any command runs
	mentions.use(holder.data)

	_ = run(holder, "add", "release")
	_ = run(holder, "note", "1", "waiting on @alpha")

	assert "alpha#1:2" in run(holder, "list")
	assert "alpha#1:2" in run(holder, "check", "1")


#
# The shared machinery
#


def test_todos_and_projects_are_selected_the_same_way(tmp_path: Path):
	from tests.helpers import SAMPLE, make_projects

	from tracker.core.todos import TODOS
	from tracker.core.entries import resolve_selection as resolve
	from tracker.core.selection import PROJECTS

	isolate(tmp_path)

	settings = make_settings(projects__number_preference="id")

	projects = make_projects(*SAMPLE)
	todos = {
		str(index): new_todo(name, status=status, todo_id=index)
		for index, (name, status) in enumerate(
			(("alpha", "current"), ("beta", "archived"), ("gamma", "todo")), 1
		)
	}

	for selector in ("all", "1", "#1", "i:1", "1-2", "1+1", "s:current", "alpha"):
		wanted = list(resolve(projects, settings, [selector], PROJECTS, quiet=True)[1])
		found = list(resolve(todos, settings, [selector], TODOS, quiet=True)[1])

		assert wanted == found == [], selector


def test_a_todo_listing_takes_the_usual_filters(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "write the changelog")
	_ = run(holder, "add", "fix the daemon")
	_ = run(holder, "1", "nt", "before friday")

	assert "changelog" in run(holder, "list", "r:^write")
	assert "daemon" not in run(holder, "list", "r:^write")

	assert "changelog" in run(holder, "list", "friday")
	assert "daemon" in run(holder, "list", "-m:changelog")


def capture(function: object, *args: object) -> str:
	stream = io.StringIO()

	with redirect_stdout(stream):
		_ = function(*args)  # pyright: ignore[reportCallIssue]

	return stream.getvalue()


def test_a_project_check_names_the_todos_about_it(tmp_path: Path):
	from tracker.ui import mentions
	from tracker.cli.commands import command_check

	from tests.helpers import SAMPLE, make_projects

	holder = context(tmp_path)
	holder.data = make_projects(*SAMPLE)

	mentions.use(holder.data)

	_ = run(holder, "add", "rewrite @alpha")
	_ = run(holder, "add", "something else")
	_ = run(holder, "note", "2", "after @beta lands")

	shown = capture(command_check, holder, ["alpha"])

	assert "Todos" in shown
	assert "rewrite @alpha" in shown
	assert "something else" not in shown

	assert "something else" in capture(command_check, holder, ["beta"])


def test_a_todo_check_names_the_projects_it_is_about(tmp_path: Path):
	from tracker.ui import mentions

	from tests.helpers import SAMPLE, make_projects

	holder = context(tmp_path)
	holder.data = make_projects(*SAMPLE)

	mentions.use(holder.data)

	_ = run(holder, "add", "rewrite @alpha")
	_ = run(holder, "note", "1", "with @gamma alongside")

	shown = run(holder, "check", "1")

	assert "Projects" in shown
	assert "alpha" in shown
	assert "gamma" in shown
	assert "beta" not in shown


def test_a_todo_that_names_nothing_keeps_the_check_quiet(tmp_path: Path):
	from tracker.ui import mentions

	from tests.helpers import SAMPLE, make_projects

	holder = context(tmp_path)
	holder.data = make_projects(*SAMPLE)

	mentions.use(holder.data)

	_ = run(holder, "add", "nothing to do with anything")

	assert "Projects" not in run(holder, "check", "1")


#
# What the two kinds now share
#


def test_removing_everything_takes_one_answer(tmp_path: Path):
	holder = context(tmp_path)

	for name in ("first", "second", "third"):
		_ = run(holder, "add", name)

	assert "removed 3 entries" in run(holder, "remove", "all")
	assert load_todos(holder.settings) == {}


def test_a_status_keeps_the_case_it_was_given(tmp_path: Path):
	holder = context(tmp_path)

	_ = run(holder, "add", "read the manual")
	_ = run(holder, "1", "st", "Blocked")

	assert load_todos(holder.settings)["1"]["status"] == "Blocked"


def test_both_kinds_answer_the_same_commands():
	from tracker.cli.todo import TODO
	from tracker.cli.commands import PROJECT

	shared = ("check", "show", "remove", "edit", "field", "statuses")

	for name in shared:
		assert getattr(type(PROJECT), name) is getattr(type(TODO), name), name
