from tests.helpers import make_projects, make_settings

from tracker.ui.render import project_name, render_rows
from tracker.util.text import abbreviate, shorten, truncate, visible_length, words


# Might as well use one of my own lol
LONG = "von-neumann-machine-simulator"
CAMEL = "VonNeumannMachineSimulator"


def test_a_name_splits_on_dashes_underscores_and_capitals():
	assert [word for word, _ in words(LONG)] == [
		"von",
		"neumann",
		"machine",
		"simulator",
	]
	assert [word for word, _ in words(CAMEL)] == [
		"Von",
		"Neumann",
		"Machine",
		"Simulator",
	]
	assert [word for word, _ in words("von_neumann.machine sim")] == [
		"von",
		"neumann",
		"machine",
		"sim",
	]


def test_abbreviating_shortens_every_word_and_keeps_the_separators():
	assert abbreviate(CAMEL, 12) == "VonNeuMacSim"
	assert abbreviate(LONG, 16) == "von-neum-mac-sim"
	assert abbreviate("von_neumann_machine_simulator", 16) == "von_neum_mac_sim"
	assert len(abbreviate(LONG, 13)) <= 13


def test_a_name_that_already_fits_is_never_touched():
	for width in (len(LONG), len(LONG) + 10):
		assert abbreviate(LONG, width) == LONG
		assert shorten(LONG, width) == LONG

	assert abbreviate(LONG, 0) == LONG
	assert shorten(LONG, 0) == LONG


def test_truncating_cuts_on_a_word_boundary():
	assert shorten(LONG, 14) == "von-neumann..."
	assert shorten(CAMEL, 14) == "VonNeumann..."
	assert shorten("download-favourite-discord-gifs", 20) == "download..."
	assert len(shorten(LONG, 14)) <= 14


def test_the_continuator_can_be_anything():
	assert shorten(LONG, 12, "~") == "von-neumann~"
	assert shorten(LONG, 12, "") == "von-neumann"


def test_a_single_word_name_still_fits_the_width():
	assert len(shorten("supercalifragilistic", 8)) == 8
	assert len(abbreviate("supercalifragilistic", 8)) == 8


def test_the_style_setting_picks_how_a_name_is_shortened():
	full = make_settings(display__name_max_width=0)
	cut = make_settings(display__name_max_width=14)
	short = make_settings(display__name_max_width=12, display__name_style="abbreviate")
	off = make_settings(display__name_max_width=12, display__name_style="full")

	path = f"/code/{CAMEL}"

	assert project_name(path, full) == CAMEL
	assert project_name(path, cut) == "VonNeumann..."
	assert project_name(path, short) == "VonNeuMacSim"
	assert project_name(path, off) == CAMEL


def test_a_shortened_name_reaches_the_table():
	projects = make_projects((f"/code/{LONG}", "dev", "2026-01-01 00:00:00", ""))

	settings = make_settings(
		display__columns=["name"],
		display__show_headers=False,
		display__name_max_width=16,
		display__name_style="abbreviate",
	)

	assert render_rows(projects.items(), settings, width=80) == ["von-neum-mac-sim"]


def test_truncation_counts_visible_characters_only():
	painted = "\033[90mhello world\033[0m"

	assert visible_length(painted) == 11
	assert visible_length(truncate(painted, 8)) == 8
	assert truncate(painted, 8).endswith("\033[0m")


def test_a_name_that_starts_with_a_separator_keeps_it():
	assert [word for word, _ in words(".my-project")] == ["", "my", "project"]
	assert [separator for _, separator in words(".my-project")] == [".", "-", ""]

	assert shorten(".my-project", 8) == ".my..."
	assert shorten("_private-repo", 9) == "_priva..."
	assert abbreviate(".config-stuff", 9).startswith(".")


def test_every_width_terminates_and_fits():
	names = (
		".my-project",
		"_private-repo",
		".dot-files",
		"---",
		".",
		"a",
		"von-neumann-machine-simulator",
		"VonNeumannMachineSimulator",
	)

	for name in names:
		for width in range(1, len(name) + 3):
			for shortened in (abbreviate(name, width), shorten(name, width)):
				assert len(shortened) <= max(width, 1), (name, width, shortened)


def test_a_budget_that_fits_keeps_every_word_whole():
	assert abbreviate("a-b-c", 5) == "a-b-c"
	assert abbreviate("a-b-c", 99) == "a-b-c"
