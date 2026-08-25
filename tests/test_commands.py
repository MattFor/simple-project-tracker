import io
import os

from pathlib import Path
from collections.abc import Callable
from contextlib import redirect_stdout

from tests.helpers import SAMPLE, make_projects, make_settings

from tracker.cli.app import main
from tracker.cli.commands import Context, command_list, command_show


def context(tmp_path: Path, **overrides: object) -> Context:
	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")

	return Context(settings=make_settings(**overrides), data=make_projects(*SAMPLE))


def output(function: Callable[..., object], *args: object) -> str:
	stream = io.StringIO()

	with redirect_stdout(stream):
		_ = function(*args)

	return stream.getvalue()


def listed(shown: str) -> set[str]:
	return {name for name in ("alpha", "beta", "gamma") if name in shown}


def test_a_limit_keyword_lists_everything(tmp_path: Path):
	holder = context(tmp_path, display__list_limit=1)

	assert len(listed(output(command_list, holder, []))) == 1

	for keyword in ("all", "a", "max", "full", "0"):
		assert listed(output(command_list, holder, [keyword])) == {
			"alpha",
			"beta",
			"gamma",
		}


def test_a_limit_keyword_ignores_the_configured_filter(tmp_path: Path):
	holder = context(tmp_path, display__filter=["-s:archived"])

	assert listed(output(command_list, holder, [])) == {"alpha", "gamma"}

	for keyword in ("all", "a", "max", "full"):
		assert listed(output(command_list, holder, [keyword])) == {
			"alpha",
			"beta",
			"gamma",
		}


def test_all_shows_the_filtered_out_projects_too(tmp_path: Path):
	holder = context(tmp_path, display__filter=["-s:archived"], display__list_limit=1)

	assert listed(output(command_show, holder, ["all"])) == {"alpha", "beta", "gamma"}


def test_a_filter_given_on_the_command_line_still_applies_to_all(tmp_path: Path):
	holder = context(tmp_path, display__filter=["-s:archived"])

	shown = output(command_list, holder, ["all", "-s:todo"])

	assert listed(shown) == {"alpha", "beta"}


def test_a_bare_project_shows_everything_about_it(tmp_path: Path):
	holder = context(tmp_path)

	shown = output(command_show, holder, ["beta"])

	assert "Tracking" in shown
	assert "Location" in shown


def test_a_bare_selection_of_several_shows_one_row_each(tmp_path: Path):
	holder = context(tmp_path)

	shown = output(command_show, holder, ["/home/user/code"])

	assert "Tracking" not in shown
	assert listed(shown) == {"alpha", "beta", "gamma"}


def test_all_lists_instead_of_describing_every_project(tmp_path: Path):
	holder = context(tmp_path, display__list_limit=1)

	shown = output(command_show, holder, ["all"])

	assert "Tracking" not in shown
	assert listed(shown) == {"alpha", "beta", "gamma"}


def test_an_unknown_command_is_reported(tmp_path: Path):
	os.environ["TRACKER_DATA"] = str(tmp_path / "empty.pkl")

	stream = io.StringIO()

	with redirect_stdout(stream):
		status = main(["nonsense-project"])

	assert status == 1
	assert "was not found" in stream.getvalue()


def test_version_and_help_always_work(tmp_path: Path):
	os.environ["TRACKER_DATA"] = str(tmp_path / "empty.pkl")

	for arguments in (["version"], ["help"], ["help", "names"], ["--help"]):
		stream = io.StringIO()

		with redirect_stdout(stream):
			status = main(arguments)

		assert status == 0
		assert stream.getvalue().strip()


def test_adding_a_moved_project_keeps_its_entry(tmp_path: Path):
	from tracker.cli.commands import command_add, command_init

	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")

	code = tmp_path / "code"
	(code / "alpha" / ".git").mkdir(parents=True)

	holder = Context(settings=make_settings(), data={})

	_ = output(command_init, holder, [str(code)])

	old = str(code / "alpha")
	holder.data[old]["status"] = "dev"

	kept = holder.data[old]["id"]

	_ = (code / "alpha").rename(code / "beta")

	shown = output(command_add, holder, [str(code / "beta")])

	assert "moved" in shown
	assert old not in holder.data
	assert holder.data[str(code / "beta")]["id"] == kept
	assert holder.data[str(code / "beta")]["status"] == "dev"


def status_sample(tmp_path: Path) -> Context:
	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")

	return Context(
		settings=make_settings(sorting__by="name", sorting__direction="ascending"),
		data=make_projects(
			("/code/alpha", "stable", "2026-01-05 10:00:00", ""),
			("/code/beta", "stable", "2026-01-04 10:00:00", ""),
			("/code/gamma", "dev", "2026-01-03 10:00:00", ""),
		),
	)


def test_a_word_that_names_no_project_is_tried_as_a_status(tmp_path: Path):
	holder = status_sample(tmp_path)

	shown = output(command_show, holder, ["stable"])

	assert "not found" not in shown
	assert "alpha" in shown and "beta" in shown
	assert "gamma" not in shown


def test_a_status_that_matches_one_project_still_shows_everything(tmp_path: Path):
	holder = status_sample(tmp_path)

	shown = output(command_show, holder, ["dev"])

	assert "Tracking" in shown
	assert "gamma" in shown


def test_a_project_name_wins_over_a_status_of_the_same_name(tmp_path: Path):
	holder = status_sample(tmp_path)

	holder.data.update(make_projects(("/code/stable", "dev", "2026-01-02 10:00:00", "")))

	shown = output(command_show, holder, ["stable"])

	assert "/code/stable" in shown
	assert "alpha" not in shown


def test_a_word_that_is_neither_is_still_an_error(tmp_path: Path):
	holder = status_sample(tmp_path)

	stream = io.StringIO()

	with redirect_stdout(stream):
		status = command_show(holder, ["nonsense"])

	assert status == 1
	assert "was not found" in stream.getvalue()


def test_a_selector_that_resolved_nothing_is_still_reported(tmp_path: Path):
	holder = status_sample(tmp_path)

	stream = io.StringIO()

	with redirect_stdout(stream):
		status = command_show(holder, ["alpha", "nonsense"])

	shown = stream.getvalue()

	assert status == 0
	assert "nonsense' was not found" in shown
	assert "alpha" in shown


def test_editing_without_a_field_says_so(tmp_path: Path):
	from tracker.cli.commands import command_edit

	holder = status_sample(tmp_path)

	stream = io.StringIO()

	with redirect_stdout(stream):
		status = command_edit(holder, ["alpha"])

	assert status == 1
	assert "requires a field" in stream.getvalue()


def test_an_edited_note_shows_its_colours(tmp_path: Path):
	from tracker.ui.ansi import C
	from tracker.cli.commands import command_edit

	holder = status_sample(tmp_path)

	C.set_enabled(True)

	try:
		first = output(command_edit, holder, ["alpha", "note", "{red}broken{/} friday"])
		second = output(command_edit, holder, ["alpha", "note", "{green}fixed{/}"])
	finally:
		C.set_enabled(False)

	assert "{red}" not in first
	assert "\033[31mbroken" in first

	# The value it replaces is painted the same way
	assert "{red}" not in second and "{green}" not in second
	assert "\033[31mbroken" in second
	assert "\033[32mfixed" in second


def test_removing_a_project_leaves_the_other_numbers_alone(tmp_path: Path):
	from tracker.cli.commands import command_remove
	from tracker.core.selection import temporary_ids
	from tracker.ui.render import print_projects

	holder = status_sample(tmp_path)
	holder.assume_yes = True

	_ = output(print_projects, holder.data, holder.settings)

	numbering = temporary_ids(holder.data, holder.settings)

	assert numbering == {"/code/alpha": 1, "/code/beta": 2, "/code/gamma": 3}

	_ = output(command_remove, holder, ["beta"])

	assert temporary_ids(holder.data, holder.settings) == {
		"/code/alpha": 1,
		"/code/gamma": 3,
	}


def test_a_scan_reports_what_it_actually_refreshed(tmp_path: Path):
	from tracker.cli.commands import command_init

	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")

	one = tmp_path / "one"
	two = tmp_path / "two"

	for root, name in ((one, "alpha"), (one, "beta"), (two, "gamma")):
		(root / name / ".git").mkdir(parents=True)

	holder = Context(settings=make_settings(), data={})

	assert "refreshed" not in output(command_init, holder, [str(one)])

	# Nothing under one/ was scanned again; nothing was refreshed
	shown = output(command_init, holder, [str(two)])

	assert "added 1 project, 3 tracked" in shown
	assert "refreshed" not in shown

	assert "refreshed 2" in output(command_init, holder, [str(one)])
