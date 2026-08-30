from pathlib import Path

from tracker.cli.app import extract_flags, fuse, split


def test_a_bare_name_becomes_a_lookup():
	assert split(["tracker"]) == [("show", ["tracker"])]


def test_commands_can_be_chained():
	assert split(["list", "5", "version"]) == [("list", ["5"]), ("version", [])]


def test_free_text_commands_swallow_the_rest():
	assert split(["add", "~/code", "active", "a note with list in it"]) == [
		("add", ["~/code", "active", "a note with list in it"])
	]

	assert split(["edit", "3", "note", "check this remove that"]) == [
		("edit", ["3", "note", "check this remove that"])
	]


def test_dashed_aliases_are_accepted():
	assert split(["--list"]) == [("list", [])]
	assert split(["-h"]) == [("help", [])]


def test_check_and_settings_aliases_do_not_collide():
	assert split(["c"])[0][0] == "check"
	assert split(["cc"])[0][0] == "check"
	assert split(["s"])[0][0] == "settings"
	assert split(["config"])[0][0] == "settings"


def test_flags_are_pulled_out_from_anywhere():
	args, flags = extract_flags(["list", "--verbose", "5"])

	assert args == ["list", "5"]
	assert flags["verbose"] is True

	args, flags = extract_flags(["remove", "all", "-y"])

	assert args == ["remove", "all"]
	assert flags["yes"] is True

	args, flags = extract_flags(["list", "--no-colour"])

	assert flags["colour"] is False


def test_flags_inside_a_note_stay_in_the_note():
	args, flags = extract_flags(["edit", "3", "note", "yes", "verbose"])

	assert args == ["edit", "3", "note", "yes", "verbose"]
	assert flags["verbose"] is False


def test_a_project_may_come_before_its_command():
	assert split(["tracker", "check"]) == [("check", ["tracker"])]
	assert split(["12", "path"]) == [("path", ["12"])]
	assert split(["12", "edit", "status", "active"]) == [
		("edit", ["12", "status", "active"])
	]


def test_a_project_before_a_subjectless_command_stays_a_lookup():
	assert split(["tracker", "stats"]) == [("show", ["tracker"]), ("stats", [])]


def test_note_and_status_are_commands_of_their_own():
	assert split(["note", "12", "review sunday"]) == [("note", ["12", "review sunday"])]
	assert split(["12", "n", "review", "sunday"]) == [
		("note", ["12", "review", "sunday"])
	]
	assert split(["12", "st", "blocked"]) == [("status", ["12", "blocked"])]


def test_short_status_does_not_shadow_settings_or_stats():
	assert split(["s"])[0][0] == "settings"
	assert split(["stat"])[0][0] == "stats"
	assert split(["st"])[0][0] == "status"


def test_flags_inside_a_bare_note_stay_in_the_note():
	args, flags = extract_flags(["3", "note", "yes", "verbose"])

	assert args == ["3", "note", "yes", "verbose"]
	assert flags["verbose"] is False


def test_sub_actions_are_not_mistaken_for_commands():
	assert split(["settings", "path"]) == [("settings", ["path"])]
	assert split(["settings", "edit"]) == [("settings", ["edit"])]
	assert split(["settings", "set", "sorting.by", "name"]) == [
		("settings", ["set", "sorting.by", "name"])
	]
	assert split(["daemon", "status"]) == [("daemon", ["status"])]
	assert split(["daemon", "restart"]) == [("daemon", ["restart"])]
	assert split(["daemon", "log", "40"]) == [("daemon", ["log", "40"])]


def test_a_double_dash_ends_the_options():
	args, flags = extract_flags(["note", "3", "--", "--verbose", "-y"])

	assert args == ["note", "3", "--", "--verbose", "-y"]
	assert flags["verbose"] is False
	assert flags["yes"] is False


def test_a_double_dash_stops_command_matching():
	assert split(["note", "3", "--", "check", "the", "list"]) == [
		("note", ["3", "check", "the", "list"])
	]

	assert split(["check", "--", "list"]) == [("check", ["list"])]


def test_only_the_first_double_dash_is_consumed():
	assert split(["note", "3", "--", "a", "--", "b"]) == [("note", ["3", "a", "--", "b"])]


def test_a_command_fuses_with_its_own_action():
	assert fuse("dst") == ("daemon", "st")
	assert fuse("ds") == ("daemon", "s")
	assert fuse("sg") == ("settings", "g")
	assert fuse("ss") == ("settings", "s")
	assert fuse("fl") == ("forget", "l")
	assert fuse("daemonstatus") == ("daemon", "status")


def test_fusing_leaves_ordinary_words_alone():
	for token in ("abba", "alpha", "tracker", "list", "n", "x", "", "sx", "zz"):
		assert fuse(token) is None


def test_fused_commands_split_like_the_spaced_form():
	assert split(["dst"]) == split(["daemon", "st"])
	assert split(["sg", "sorting.by"]) == [("settings", ["g", "sorting.by"])]
	assert split(["dl", "20"]) == [("daemon", ["l", "20"])]


def test_fusing_never_touches_free_text():
	assert split(["note", "5", "ds", "sp"]) == [("note", ["5", "ds", "sp"])]
	assert split(["add", "~/code", "ds"]) == [("add", ["~/code", "ds"])]
	assert split(["check", "--", "ds"]) == [("check", ["ds"])]


def test_help_can_be_asked_for_before_or_after_a_command():
	assert split(["help"]) == [("help", [])]
	assert split(["help", "list"]) == [("help", ["list"])]
	assert split(["list", "help"]) == [("help", ["list"])]
	assert split(["daemon", "help"]) == [("help", ["daemon"])]
	assert split(["settings", "set", "help"]) == [("help", ["settings"])]
	assert split(["l", "-h"]) == [("help", ["list"])]


def test_a_greedy_command_still_answers_a_bare_help():
	assert split(["status", "help"]) == [("help", ["status"])]
	assert split(["edit", "help"]) == [("help", ["edit"])]


def test_help_inside_free_text_stays_free_text():
	assert split(["note", "5", "help", "me"]) == [("note", ["5", "help", "me"])]
	assert split(["note", "5", "--", "help"]) == [("note", ["5", "help"])]
	assert split(["add", "~/code", "todo", "help"]) == [
		("add", ["~/code", "todo", "help"])
	]


def test_help_takes_a_topic_that_is_not_a_command():
	assert split(["help", "statuses"]) == [("help", ["statuses"])]
	assert split(["help", "project", "selection"]) == [("help", ["project", "selection"])]


def test_usage_is_only_recorded_when_it_is_turned_on():
	from tracker.cli.entries import Context
	from tests.helpers import SAMPLE, make_projects, make_settings

	for enabled in (True, False):
		projects = make_projects(*SAMPLE)

		context = Context(
			settings=make_settings(projects__track_usage=enabled), data=projects
		)

		assert context.mark_used(projects) is enabled
		assert context.pending is enabled

		stamped = [project for project in projects.values() if "last_used" in project]

		assert bool(stamped) is enabled


def test_nothing_selected_is_never_stamped():
	from tests.helpers import make_settings
	from tracker.cli.entries import Context

	context = Context(settings=make_settings(), data={})

	assert context.mark_used({}) is False
	assert context.pending is False


def test_the_decorator_saves_what_a_command_used(tmp_path: Path):
	import os

	from tracker.cli.entries import Context, marks_used
	from tests.helpers import SAMPLE, make_projects, make_settings

	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")

	projects = make_projects(*SAMPLE)
	context = Context(settings=make_settings(), data=projects)

	@marks_used
	def handler(inner: Context, args: list[str]) -> int:
		del args

		_ = inner.select(["alpha"])

		return 0

	assert handler(context, []) == 0
	assert context.pending is False
	assert (tmp_path / "data.pkl").is_file()


def test_editing_only_a_field_fuses_into_edit():
	assert split(["11", "es", "shelf"]) == [("edit", ["11", "s", "shelf"])]
	assert split(["t:11", "es", "stable"]) == [("edit", ["t:11", "s", "stable"])]
	assert split(["11", "en", "review", "later"]) == [
		("edit", ["11", "n", "review", "later"])
	]
	assert fuse("est") == ("edit", "st")


def test_a_fused_edit_keeps_its_free_text():
	args, flags = extract_flags(["11", "en", "yes", "verbose"])

	assert args == ["11", "en", "yes", "verbose"]
	assert flags["verbose"] is False

	assert split(["11", "en", "check", "the", "list"]) == [
		("edit", ["11", "n", "check", "the", "list"])
	]


def test_all_asks_a_listing_for_everything():
	assert split(["list", "all"]) == [("list", ["all"])]
	assert split(["l", "a"]) == [("list", ["a"])]
	assert split(["all"]) == [("show", ["all"])]


def test_set_status_and_set_note_have_their_own_short_forms():
	assert split(["12", "ss", "blocked"]) == [("status", ["12", "blocked"])]
	assert split(["12", "sn", "review", "sunday"]) == [
		("note", ["12", "review", "sunday"])
	]
	assert split(["ss", "12", "blocked"]) == [("status", ["12", "blocked"])]


def test_settings_set_keeps_its_own_short_forms():
	for arguments in (
		["sset", "sorting.by", "name"],
		["s", "set", "sorting.by", "name"],
		["settings", "set", "sorting.by", "name"],
	):
		assert split(arguments) == [("settings", ["set", "sorting.by", "name"])]
