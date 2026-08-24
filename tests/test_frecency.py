from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta

from tests.helpers import make_projects, make_settings

from tracker.core import frecency as scoring
from tracker.core.selection import select_projects
from tracker.core.frecency import best_match, decay, frecency, score_of

NOW = datetime(2026, 8, 24, 12, 0, 0)


@contextmanager
def zoxide(scores: dict[str, float]) -> Generator[None]:
	scoring._cache["scores"] = scores

	try:
		yield
	finally:
		scoring._cache.clear()


def stamp(gap: timedelta) -> str:
	return (NOW - gap).strftime("%Y-%m-%d %H:%M:%S")


def used(uses: int, gap: timedelta):
	projects = make_projects(("/code/alpha", "dev", "2026-08-01 00:00:00", ""))

	projects["/code/alpha"]["uses"] = uses
	projects["/code/alpha"]["last_used"] = stamp(gap)

	return projects["/code/alpha"]


def test_the_decay_matches_zoxide():
	assert decay(60.0) == 4.0
	assert decay(3 * 3600.0) == 2.0
	assert decay(3 * 86400.0) == 0.5
	assert decay(30 * 86400.0) == 0.25


def test_a_score_is_uses_weighted_by_how_recently():
	settings = make_settings()

	assert frecency(used(3, timedelta(minutes=5)), settings, NOW) == 12.0
	assert frecency(used(3, timedelta(hours=5)), settings, NOW) == 6.0
	assert frecency(used(3, timedelta(days=3)), settings, NOW) == 1.5
	assert frecency(used(3, timedelta(days=30)), settings, NOW) == 0.75


def test_a_project_never_used_scores_nothing():
	projects = make_projects(("/code/alpha", "dev", "2026-08-01 00:00:00", ""))
	settings = make_settings()

	assert frecency(projects["/code/alpha"], settings, NOW) == 0.0


def test_a_use_without_a_timestamp_still_counts_a_little():
	projects = make_projects(("/code/alpha", "dev", "2026-08-01 00:00:00", ""))
	projects["/code/alpha"]["uses"] = 8

	assert frecency(projects["/code/alpha"], make_settings(), NOW) == 2.0


def sample():
	projects = make_projects(
		("/code/relaxy-private", "dev", "2026-08-01 00:00:00", ""),
		("/code/relaxy-public", "dev", "2026-08-01 00:00:00", ""),
		("/code/relaxy-dashboard", "dev", "2026-08-01 00:00:00", ""),
	)

	return projects


def test_the_best_match_needs_a_clear_winner():
	projects = sample()
	settings = make_settings()

	assert best_match(list(projects.items()), settings, "frecency", NOW) is None

	projects["/code/relaxy-public"]["uses"] = 2
	projects["/code/relaxy-public"]["last_used"] = stamp(timedelta(minutes=1))

	best = best_match(list(projects.items()), settings, "frecency", NOW)

	assert best is not None and best[0] == "/code/relaxy-public"

	projects["/code/relaxy-private"]["uses"] = 2
	projects["/code/relaxy-private"]["last_used"] = stamp(timedelta(minutes=1))

	assert best_match(list(projects.items()), settings, "frecency", NOW) is None


def test_zoxide_scores_settle_a_partial_name():
	projects = sample()
	settings = make_settings(projects__conflict_resolution_preference="zoxide")

	with zoxide({"/code/relaxy-dashboard": 18.0, "/code/relaxy-private": 248.0}):
		assert (
			score_of(
				"/code/relaxy-private",
				projects["/code/relaxy-private"],
				settings,
				"zoxide",
			)
			== 248.0
		)

		selected = select_projects(projects, settings, ["relaxy"], quiet=True)

	assert list(selected) == ["/code/relaxy-private"]


def test_zoxide_falls_back_to_what_tracker_knows():
	projects = sample()

	projects["/code/relaxy-dashboard"]["uses"] = 5
	projects["/code/relaxy-dashboard"]["last_used"] = stamp(timedelta(minutes=2))

	settings = make_settings(projects__conflict_resolution_preference="zoxide")

	with zoxide({}):
		selected = select_projects(projects, settings, ["relaxy"], quiet=True)

	assert list(selected) == ["/code/relaxy-dashboard"]


def test_an_unknowable_clash_is_still_reported():
	settings = make_settings(projects__conflict_resolution_preference="zoxide")

	with zoxide({}):
		assert select_projects(sample(), settings, ["relaxy"], quiet=True) == {}


def test_a_prefix_match_is_preferred_before_scoring():
	projects = sample()
	projects["/code/not-relaxy-at-all"] = make_projects(
		("/code/not-relaxy-at-all", "dev", "2026-08-01 00:00:00", "")
	)["/code/not-relaxy-at-all"]

	projects["/code/relaxy-public"]["uses"] = 3
	projects["/code/relaxy-public"]["last_used"] = stamp(timedelta(minutes=1))

	settings = make_settings(projects__conflict_resolution_preference="zoxide")

	with zoxide({"/code/not-relaxy-at-all": 999.0}):
		selected = select_projects(projects, settings, ["relaxy"], quiet=True)

	assert list(selected) == ["/code/relaxy-public"]
