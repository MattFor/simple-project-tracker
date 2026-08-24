from typing import Any

from tests.helpers import SAMPLE, make_projects, make_settings

from tracker.ui.render import render_rows
from tracker.core.selection import temporary_ids
from tracker.util.text import human_size, relative_time, truncate, wrap


def sample():
	return make_projects(*SAMPLE)


def rows(width: int, **overrides: Any) -> list[str]:
	settings = make_settings(
		sorting__by="name",
		sorting__direction="ascending",
		display__columns=["tid", "name", "status"],
		display__vertical_separator=" | ",
		**overrides,
	)

	projects = sample()

	return render_rows(
		sorted(projects.items()),
		settings,
		temporary_ids(projects, settings),
		width=width,
	)


def test_short_note_shares_the_project_line():
	lines = rows(120)

	alpha = next(line for line in lines if "alpha" in line)

	assert "short note" in alpha


def test_note_moves_below_when_the_terminal_is_narrow():
	lines = rows(40)

	index = next(i for i, line in enumerate(lines) if "alpha" in line)

	assert "short note" not in lines[index]
	assert "short note" in lines[index + 1]


def test_long_note_moves_below_and_wraps():
	lines = rows(80)

	index = next(i for i, line in enumerate(lines) if "gamma" in line)

	assert "much longer note" not in lines[index]
	assert "much longer note" in lines[index + 1]
	assert all(len(line) <= 80 for line in lines)


def test_note_column_header_appears_only_with_inline_notes():
	assert "NOTE" in rows(120)[0]
	assert "NOTE" not in rows(40)[0]


def test_below_position_never_shares_the_line():
	lines = rows(200, display__note_position="below")

	alpha = next(i for i, line in enumerate(lines) if "alpha" in line)

	assert "short note" not in lines[alpha]
	assert "short note" in lines[alpha + 1]


def test_inline_position_shortens_instead_of_wrapping():
	lines = rows(90, display__note_position="inline")

	gamma = next(line for line in lines if "gamma" in line)

	assert "..." in gamma
	assert len(gamma) <= 90


def test_notes_can_be_switched_off():
	lines = rows(200, display__show_notes=False)

	assert not any("short note" in line for line in lines)


def test_columns_shrink_before_the_line_overflows():
	settings = make_settings(
		display__columns=["name", "path"],
		display__show_headers=False,
		display__show_notes=False,
	)

	projects = sample()

	lines = render_rows(sorted(projects.items()), settings, width=40)

	assert all(len(line) <= 40 for line in lines)


def test_no_rows_renders_nothing():
	assert render_rows([], make_settings()) == []


def test_multi_line_notes_are_flattened_when_inline():
	projects = make_projects(
		("/code/a", "x", "2026-01-01 00:00:00", "line one\nline two")
	)

	settings = make_settings(display__columns=["name"], display__show_headers=False)

	lines = render_rows(sorted(projects.items()), settings, width=120)

	assert len(lines) == 1
	assert "line one" in lines[0] and "line two" in lines[0]


def test_text_helpers():
	assert truncate("abcdefgh", 5) == "ab..."
	assert truncate("abc", 5) == "abc"
	assert wrap("a bb ccc", 4) == ["a bb", "ccc"]
	assert human_size(2048) == "2.0 KiB"
	assert "ago" in relative_time(__import__("datetime").datetime(2020, 1, 1))


def test_a_format_string_replaces_the_columns():
	lines = rows(
		120, display__format="$tid. $name [$status]", display__show_headers=False
	)

	assert lines[0].startswith("1. alpha [current")


def test_a_format_string_stays_aligned():
	lines = rows(120, display__format="$name|$status|", display__show_headers=False)

	bars = [line.index("|") for line in lines if "|" in line]

	assert len(set(bars)) == 1


def test_a_format_field_can_be_right_aligned():
	left = rows(120, display__format="$tid|", display__show_headers=True)[2]
	right = rows(120, display__format="$>tid|", display__show_headers=True)[2]

	assert left.startswith("1  |")
	assert right.startswith("  1|")


def test_an_unknown_format_field_stays_literal():
	lines = rows(120, display__format="$name $nope", display__show_headers=False)

	assert "$nope" in lines[0]


def test_a_format_string_can_place_the_note_itself():
	lines = rows(120, display__format="$name -> $note", display__show_headers=False)

	alpha = next(line for line in lines if "alpha" in line)

	assert "-> short note" in alpha
	assert len([line for line in lines if "short note" in line]) == 1


def test_braces_separate_a_field_from_the_text_after_it():
	lines = rows(120, display__format="${tid}x $name", display__show_headers=False)

	assert lines[0].startswith("1x ")


def test_relative_times_can_be_shortened():
	from datetime import datetime, timedelta

	now = datetime(2026, 1, 10, 12, 0, 0)

	cases = (
		(timedelta(seconds=8), "just now", "now"),
		(timedelta(seconds=90), "1 minute ago", "1m ago"),
		(timedelta(minutes=8), "8 minutes ago", "8m ago"),
		(timedelta(hours=3), "3 hours ago", "3h ago"),
		(timedelta(days=2), "2 days ago", "2d ago"),
		(timedelta(days=15), "2 weeks ago", "2w ago"),
		(timedelta(days=70), "2 months ago", "2mo ago"),
		(timedelta(days=800), "2 years ago", "2y ago"),
	)

	for gap, long, short in cases:
		moment = now - gap

		assert relative_time(moment, now) == long
		assert relative_time(moment, now, short=True) == short


def test_short_relative_times_keep_the_future_direction():
	from datetime import datetime, timedelta

	now = datetime(2026, 1, 10, 12, 0, 0)

	assert relative_time(now + timedelta(hours=5), now, short=True) == "in 5h"
	assert relative_time(now + timedelta(hours=5), now) == "in 5 hours"


def test_the_relative_style_setting_reaches_the_table():
	from datetime import datetime

	stamp = datetime.now().replace(microsecond=0)
	written = stamp.strftime("%Y-%m-%d %H:%M:%S")

	projects = make_projects(("/code/alpha", "todo", written, ""))

	settings = make_settings(
		display__columns=["name", "last_touched"],
		display__relative_times=True,
		display__relative_style="short",
		display__show_headers=False,
	)

	line = render_rows(projects.items(), settings, width=80)[0]

	assert "now" in line and "just now" not in line


def test_the_last_used_column_falls_back_to_never():
	projects = make_projects(
		("/code/alpha", "todo", "2026-01-01 00:00:00", ""),
		("/code/beta", "todo", "2026-01-01 00:00:00", ""),
	)

	projects["/code/alpha"]["last_used"] = "2026-01-02 00:00:00"

	settings = make_settings(
		display__columns=["name", "last_used"], display__show_headers=False
	)

	lines = render_rows(projects.items(), settings, width=80)

	assert "2026-01-02 00:00:00" in lines[0]
	assert "never" in lines[1]


def test_a_note_may_colour_itself():
	from tracker.ui.ansi import C, markup

	projects = make_projects(
		("/code/alpha", "dev", "2026-01-01 00:00:00", "{red}broken{/} since friday")
	)

	settings = make_settings(display__columns=["name"], display__show_headers=False)

	C.set_enabled(False)

	try:
		line = render_rows(projects.items(), settings, width=120)[0]

		assert line.endswith("broken since friday")
		assert markup("{gray}a{/}b") == "ab"

		C.set_enabled(True)

		painted = render_rows(projects.items(), settings, width=120)[0]

		assert "\033[31m" in painted
		assert "{red}" not in painted
	finally:
		C.set_enabled(False)


def test_an_unknown_brace_word_stays_in_the_note():
	projects = make_projects(
		("/code/alpha", "dev", "2026-01-01 00:00:00", "wait for {thing}")
	)

	settings = make_settings(display__columns=["name"], display__show_headers=False)

	assert "{thing}" in render_rows(projects.items(), settings, width=120)[0]


def test_a_coloured_note_still_fits_the_terminal():
	from tracker.ui.ansi import C
	from tracker.util.text import visible_length

	projects = make_projects(
		("/code/alpha", "dev", "2026-01-01 00:00:00", "{y}" + "long note " * 10)
	)

	settings = make_settings(
		display__columns=["name"],
		display__show_headers=False,
		display__note_position="inline",
	)

	C.set_enabled(True)

	try:
		line = render_rows(projects.items(), settings, width=60)[0]

		assert visible_length(line) <= 60
	finally:
		C.set_enabled(False)


def test_a_note_that_never_closes_its_colour_is_closed_for_it():
	from tracker.ui.ansi import C
	from tracker.ui.render import note_text

	projects = make_projects(("/code/alpha", "dev", "2026-01-01 00:00:00", "{red}broken"))

	C.set_enabled(True)

	try:
		painted = note_text(projects["/code/alpha"])

		assert painted.startswith("\033[31m")
		assert painted.endswith("\033[0m")
	finally:
		C.set_enabled(False)
