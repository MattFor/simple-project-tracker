import os

from pathlib import Path

from tests.helpers import SAMPLE, make_projects, make_settings

from tracker.core.models import Projects, get_id, new_project, normalise
from tracker.core.selection import (
	filter_projects,
	parse_filter,
	regex_projects,
	resolve_selection,
	search_projects,
	select_projects,
	sort_projects,
	temporary_ids,
)


def sample():
	return make_projects(*SAMPLE)


def names(projects: Projects) -> list[str]:
	return [path.rsplit("/", 1)[-1] for path in projects]


def test_ids_sort_numerically():
	projects = {}

	for number in (1, 2, 9, 10, 11):
		path = f"/code/project{number}"
		projects[path] = new_project(path, status="x", project_id=number)

	settings = make_settings(sorting__by="id", sorting__direction="ascending")

	ordered = [project["id"] for _, project in sort_projects(projects, settings)]

	assert ordered == [1, 2, 9, 10, 11]


def test_unknown_timestamps_sort_last_when_descending():
	projects = make_projects(
		("/code/a", "x", "2026-01-01 00:00:00", ""),
		("/code/b", "x", "unknown", ""),
	)

	settings = make_settings(sorting__by="last_touched", sorting__direction="descending")

	assert names(dict(sort_projects(projects, settings))) == ["a", "b"]


def test_temporary_ids_follow_the_sorted_view():
	settings = make_settings(sorting__by="name", sorting__direction="ascending")

	assert temporary_ids(sample(), settings) == {
		"/home/user/code/alpha": 1,
		"/home/user/code/beta": 2,
		"/home/user/code/gamma": 3,
	}


def test_select_by_name_and_path():
	settings = make_settings()

	assert names(select_projects(sample(), settings, ["beta"])) == ["beta"]
	assert names(select_projects(sample(), settings, ["/home/user/code/beta"])) == [
		"beta"
	]


def test_select_inclusive_range():
	settings = make_settings(sorting__by="name", sorting__direction="ascending")

	assert names(select_projects(sample(), settings, ["1-2"])) == ["alpha", "beta"]
	assert sorted(names(select_projects(sample(), settings, ["3-1"]))) == [
		"alpha",
		"beta",
		"gamma",
	]


def test_select_relative_range():
	settings = make_settings(sorting__by="name", sorting__direction="ascending")

	assert names(select_projects(sample(), settings, ["1+1"])) == ["alpha", "beta"]


def test_select_all():
	settings = make_settings()

	assert len(select_projects(sample(), settings, ["all"])) == 3


def test_out_of_range_numbers_are_ignored_not_fatal():
	settings = make_settings(sorting__by="name", sorting__direction="ascending")

	assert names(select_projects(sample(), settings, ["2-9"])) == ["beta", "gamma"]


def test_explicit_id_and_tid_prefixes():
	projects = sample()
	settings = make_settings(sorting__by="name", sorting__direction="descending")

	assert names(select_projects(projects, settings, ["@1"])) == ["gamma"]
	assert names(select_projects(projects, settings, ["#1"])) == ["alpha"]


def test_filters_include_and_exclude():
	projects = sample()

	assert names(filter_projects(projects, ["+m:beta"])) == ["beta"]
	assert names(filter_projects(projects, ["-m:beta"])) == ["alpha", "gamma"]
	assert names(filter_projects(projects, ["+r:^g"])) == ["gamma"]
	assert names(filter_projects(projects, ["-r:^g"])) == ["alpha", "beta"]


def test_invalid_filters_do_not_change_the_result():
	projects = sample()

	assert len(filter_projects(projects, ["nonsense"])) == 3
	assert len(filter_projects(projects, ["+z:beta"])) == 3
	assert len(filter_projects(projects, ["+r:[unclosed"])) == 3


def test_search_and_regex():
	projects = sample()

	matched = regex_projects(projects, "a$")

	assert names(search_projects(projects, "BET")) == ["beta"]
	assert matched is not None and names(matched) == ["alpha", "beta", "gamma"]
	assert regex_projects(projects, "[unclosed") is None


def test_get_id_skips_used_numbers():
	projects = sample()

	assert get_id(projects) == 4
	assert get_id({}) == 1


def test_normalise_repairs_damaged_entries():
	repaired = normalise(
		{
			"/code/a": {"id": 1, "tid": 5},
			"/code/b": {"id": 1},
			"not a project": "junk",
		}
	)

	assert "tid" not in repaired["/code/a"]
	assert repaired["/code/a"]["status"] == "unknown"
	assert repaired["/code/b"]["id"] != repaired["/code/a"]["id"]
	assert "not a project" not in repaired


def test_named_id_and_tid_prefixes_avoid_the_shell():
	projects = sample()
	settings = make_settings(sorting__by="name", sorting__direction="descending")

	assert names(select_projects(projects, settings, ["tid:1"])) == ["gamma"]
	assert names(select_projects(projects, settings, ["id:1"])) == ["alpha"]
	assert names(select_projects(projects, settings, ["ID=2"])) == ["beta"]


def test_short_id_and_tid_prefixes():
	projects = sample()
	settings = make_settings(sorting__by="name", sorting__direction="descending")

	assert names(select_projects(projects, settings, ["t:1"])) == ["gamma"]
	assert names(select_projects(projects, settings, ["i:1"])) == ["alpha"]
	assert names(select_projects(projects, settings, ["I:2"])) == ["beta"]


def test_a_number_falls_back_to_the_project_name():
	projects = make_projects(
		("/code/2024", "todo", "2026-01-01 00:00:00", ""),
		("/code/alpha", "todo", "2026-01-02 00:00:00", ""),
	)

	settings = make_settings(sorting__by="name", sorting__direction="ascending")

	assert names(select_projects(projects, settings, ["2024"])) == ["2024"]


def test_a_path_on_disk_is_resolved(tmp_path: Path):
	project = tmp_path / "alpha"
	project.mkdir()

	path = str(project.resolve())

	projects = make_projects((path, "todo", "2026-01-01 00:00:00", ""))
	settings = make_settings()

	relative = os.path.relpath(path)

	assert list(select_projects(projects, settings, [relative])) == [path]


def test_unresolved_selectors_are_reported():
	projects = sample()
	settings = make_settings()

	selected, unmatched = resolve_selection(
		projects, settings, ["beta", "nonsense"], quiet=True
	)

	assert names(selected) == ["beta"]
	assert unmatched == ["nonsense"]


#
# Statuses
#


def status_sample():
	return make_projects(
		("/code/alpha", "current", "2026-01-05 10:00:00", ""),
		("/code/beta", "archived", "2026-02-10 10:00:00", ""),
		("/code/gamma", "todo", "2025-12-01 10:00:00", ""),
		("/code/delta", "archive", "2025-11-01 10:00:00", ""),
	)


def test_status_filters_include_and_exclude():
	projects = status_sample()

	assert names(filter_projects(projects, ["+s:todo"])) == ["gamma"]
	assert names(filter_projects(projects, ["-s:todo"])) == ["alpha", "beta", "delta"]


def test_a_status_filter_takes_several_values():
	projects = status_sample()

	assert names(filter_projects(projects, ["+s:current,todo"])) == ["alpha", "gamma"]
	assert names(filter_projects(projects, ["-s:current,todo"])) == ["beta", "delta"]


def test_a_status_matches_by_prefix_as_well():
	projects = status_sample()

	assert names(filter_projects(projects, ["+s:arch"])) == ["beta", "delta"]


def test_command_line_filters_are_normalised():
	assert parse_filter("s:todo") == "+s:todo"
	assert parse_filter("!s:todo") == "-s:todo"
	assert parse_filter("-s:todo") == "-s:todo"
	assert parse_filter("status:todo") == "+s:todo"
	assert parse_filter("st=todo") == "+s:todo"
	assert parse_filter("+m:python") == "+m:python"
	assert parse_filter("regex:^a") == "+r:^a"


def test_ordinary_words_and_settings_are_not_filters():
	for token in ("tracker", "20", "regex", "display.list_limit=20", "sorting.by=name"):
		assert parse_filter(token) is None


def test_a_status_can_select_projects():
	projects = status_sample()
	settings = make_settings(sorting__by="name", sorting__direction="ascending")

	assert sorted(names(select_projects(projects, settings, ["s:current"]))) == ["alpha"]
	assert sorted(names(select_projects(projects, settings, ["status:arch"]))) == [
		"beta",
		"delta",
	]
	assert sorted(names(select_projects(projects, settings, ["s:todo,current"]))) == [
		"alpha",
		"gamma",
	]


def test_an_unknown_status_selects_nothing():
	projects = status_sample()
	settings = make_settings()

	selected, unmatched = resolve_selection(
		projects, settings, ["s:nonsense"], quiet=True
	)

	assert not selected
	assert unmatched == ["s:nonsense"]


def test_sorting_by_status_follows_the_configured_order():
	projects = status_sample()

	settings = make_settings(
		sorting__by="status",
		sorting__direction="ascending",
		sorting__status_order=["todo", "current"],
	)

	assert names(dict(sort_projects(projects, settings))) == [
		"gamma",
		"alpha",
		"delta",
		"beta",
	]


def test_sorting_by_status_is_alphabetical_without_an_order():
	projects = status_sample()

	settings = make_settings(sorting__by="status", sorting__direction="ascending")

	assert names(dict(sort_projects(projects, settings))) == [
		"delta",
		"beta",
		"alpha",
		"gamma",
	]


#
# Last used
#


def test_sorting_by_last_used_puts_the_never_used_last():
	projects = make_projects(
		("/code/alpha", "todo", "2026-01-01 00:00:00", ""),
		("/code/beta", "todo", "2026-01-01 00:00:00", ""),
		("/code/gamma", "todo", "2026-01-01 00:00:00", ""),
	)

	projects["/code/beta"]["last_used"] = "2026-03-01 00:00:00"
	projects["/code/gamma"]["last_used"] = "2026-02-01 00:00:00"

	settings = make_settings(sorting__by="last_used", sorting__direction="descending")

	assert names(dict(sort_projects(projects, settings))) == ["beta", "gamma", "alpha"]


#
# Numbers that are both ID/TID
#


def clashing():
	projects = make_projects(
		("/code/beta", "todo", "2026-01-01 00:00:00", ""),
		("/code/alpha", "todo", "2026-01-01 00:00:00", ""),
	)

	return projects


def test_an_ambiguous_number_is_reported_once():
	projects = clashing()
	settings = make_settings(sorting__by="name", sorting__direction="ascending")

	selected, unmatched = resolve_selection(projects, settings, ["1"], quiet=True)

	assert not selected
	assert unmatched == ["1"]


def test_the_number_preference_settles_an_ambiguous_number():
	projects = clashing()

	for preference, expected in (("id", "beta"), ("tid", "alpha")):
		settings = make_settings(
			sorting__by="name",
			sorting__direction="ascending",
			projects__number_preference=preference,
		)

		assert names(select_projects(projects, settings, ["1"], quiet=True)) == [expected]


def test_explicit_prefixes_accept_ranges():
	projects = sample()
	settings = make_settings(sorting__by="name", sorting__direction="descending")

	assert sorted(names(select_projects(projects, settings, ["t:1-2"]))) == [
		"beta",
		"gamma",
	]
	assert sorted(names(select_projects(projects, settings, ["i:1+1"]))) == [
		"alpha",
		"beta",
	]
	assert sorted(names(select_projects(projects, settings, ["@1-2"]))) == [
		"beta",
		"gamma",
	]


#
# Numbering
#


def hidden_sample():
	return make_projects(
		("/code/alpha", "dev", "2026-01-05 10:00:00", ""),
		("/code/beta", "archive", "2026-01-04 10:00:00", ""),
		("/code/gamma", "dev", "2026-01-03 10:00:00", ""),
		("/code/delta", "archive", "2026-01-02 10:00:00", ""),
		("/code/epsilon", "dev", "2026-01-01 10:00:00", ""),
	)


def test_temporary_ids_leave_no_gaps_when_a_filter_hides_projects():
	settings = make_settings(
		sorting__by="name",
		sorting__direction="ascending",
		display__filter=["-s:archive"],
	)

	numbering = temporary_ids(hidden_sample(), settings)

	assert numbering["/code/alpha"] == 1
	assert numbering["/code/epsilon"] == 2
	assert numbering["/code/gamma"] == 3


def test_a_hidden_project_is_numbered_by_whatever_shows_it():
	from tracker.core.selection import pin_projects

	settings = make_settings(
		sorting__by="name",
		sorting__direction="ascending",
		display__filter=["-s:archive"],
	)

	projects = hidden_sample()
	hidden = {path: projects[path] for path in ("/code/beta", "/code/delta")}

	assert "/code/beta" not in temporary_ids(projects, settings)

	assert pin_projects(hidden, settings) == {"/code/beta": 1, "/code/delta": 2}
	assert names(select_projects(projects, settings, [":1"])) == ["beta"]
	assert names(select_projects(projects, settings, [":2"])) == ["delta"]


def test_a_colon_is_a_shorthand_for_the_temporary_id():
	projects = sample()
	settings = make_settings(sorting__by="name", sorting__direction="descending")

	assert names(select_projects(projects, settings, [":1"])) == ["gamma"]
	assert names(select_projects(projects, settings, [":2"])) == ["beta"]
	assert sorted(names(select_projects(projects, settings, [":1-2"]))) == [
		"beta",
		"gamma",
	]


def test_a_colon_selector_never_reads_as_a_status():
	projects = sample()
	settings = make_settings()

	selected, unmatched = resolve_selection(projects, settings, [":99"], quiet=True)

	assert not selected
	assert unmatched == [":99"]
