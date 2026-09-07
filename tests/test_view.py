import os
from pathlib import Path

from tests.helpers import SAMPLE, make_projects, make_settings
from tracker.core.models import Projects
from tracker.core.selection import (
	current_numbering,
	pin_projects,
	select_projects,
	temporary_ids,
)
from tracker.core.view import load_numbering, save_numbering


def isolate(tmp_path: Path) -> None:
	os.environ["TRACKER_VIEW"] = str(tmp_path / "view.json")
	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")


def names(numbering: dict[str, int]) -> list[str]:
	return [
		path.rsplit("/", 1)[-1]
		for path, _ in sorted(numbering.items(), key=lambda item: item[1])
	]


def selected(projects: Projects) -> list[str]:
	return [path.rsplit("/", 1)[-1] for path in projects]


def test_without_a_listing_the_numbering_is_the_current_order(tmp_path: Path):
	isolate(tmp_path)

	projects = make_projects(*SAMPLE)
	settings = make_settings(sorting__by="name", sorting__direction="ascending")

	assert load_numbering(settings) is None
	assert temporary_ids(projects, settings) == current_numbering(projects, settings)


def test_a_listing_pins_the_numbering(tmp_path: Path):
	isolate(tmp_path)

	projects = make_projects(*SAMPLE)
	settings = make_settings(sorting__by="name", sorting__direction="ascending")

	pinned = pin_projects(projects, settings)

	assert names(pinned) == ["alpha", "beta", "gamma"]

	# Something reorders the projects behind our back D:
	projects["/home/user/code/gamma"]["last_touched"] = "2027-01-01 00:00:00"

	sorted_now = make_settings(
		sorting__by="last_touched", sorting__direction="descending"
	)

	assert names(current_numbering(projects, sorted_now)) == ["gamma", "beta", "alpha"]
	assert names(temporary_ids(projects, sorted_now)) == ["alpha", "beta", "gamma"]
	assert selected(select_projects(projects, sorted_now, [":1"])) == ["alpha"]


def test_a_project_the_listing_never_showed_has_no_row(tmp_path: Path):
	isolate(tmp_path)

	projects = make_projects(*SAMPLE)
	settings = make_settings(sorting__by="name", sorting__direction="ascending")

	_ = pin_projects(projects, settings)

	late = make_projects(("/home/user/code/delta", "dev", "2026-03-01 10:00:00", ""))
	projects.update(late)

	numbering = temporary_ids(projects, settings)

	assert "/home/user/code/delta" not in numbering
	assert names(pin_projects(projects, settings)) == [
		"alpha",
		"beta",
		"delta",
		"gamma",
	]


def test_a_numbering_of_another_database_is_ignored(tmp_path: Path):
	isolate(tmp_path)

	projects = make_projects(*SAMPLE)
	settings = make_settings()

	_ = pin_projects(projects, settings)

	assert load_numbering(settings) is not None

	os.environ["TRACKER_DATA"] = str(tmp_path / "other.pkl")

	assert load_numbering(settings) is None


def test_a_damaged_numbering_is_ignored(tmp_path: Path):
	isolate(tmp_path)

	view = tmp_path / "view.json"

	_ = view.write_text('{"database": "x", "order": "not a list"}')

	assert load_numbering(make_settings()) is None

	_ = view.write_text("this is not json")

	assert load_numbering(make_settings()) is None


def test_the_numbering_survives_a_round_trip(tmp_path: Path):
	isolate(tmp_path)

	settings = make_settings()
	numbering = {"/code/b": 2, "/code/a": 1, "/code/c": 3}

	assert save_numbering(numbering, settings)
	assert load_numbering(settings) == numbering


def test_a_listing_writes_the_numbering_it_printed(tmp_path: Path):
	isolate(tmp_path)

	from tracker.ui.render import print_projects

	projects = make_projects(*SAMPLE)
	settings = make_settings(sorting__by="name", sorting__direction="ascending")

	print_projects(projects, settings)

	assert names(load_numbering(settings) or {}) == ["alpha", "beta", "gamma"]


def test_the_numbering_is_whatever_was_last_printed(tmp_path: Path):
	isolate(tmp_path)

	from tracker.core.view import load_numbering
	from tracker.ui.render import print_projects

	projects = make_projects(
		("/code/alpha", "dev", "2026-01-05 10:00:00", ""),
		("/code/beta", "stable", "2026-01-04 10:00:00", ""),
		("/code/gamma", "stable", "2026-01-03 10:00:00", ""),
	)

	settings = make_settings(
		sorting__by="name",
		sorting__direction="ascending",
		display__filter=["-s:stable"],
	)

	print_projects(projects, settings)

	assert names(load_numbering(settings) or {}) == ["alpha"]

	hidden = {path: projects[path] for path in ("/code/beta", "/code/gamma")}

	assert pin_projects(hidden, settings) == {"/code/beta": 1, "/code/gamma": 2}
	assert names(temporary_ids(projects, settings)) == ["beta", "gamma"]


def test_a_limited_listing_only_numbers_the_rows_it_printed(tmp_path: Path):
	isolate(tmp_path)

	from tracker.core.view import load_numbering
	from tracker.ui.render import print_projects

	projects = make_projects(*SAMPLE)

	settings = make_settings(
		sorting__by="name", sorting__direction="ascending", display__list_limit=2
	)

	print_projects(projects, settings)

	assert names(load_numbering(settings) or {}) == ["alpha", "beta"]
