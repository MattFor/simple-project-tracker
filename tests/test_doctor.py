import os
from pathlib import Path

import pytest

from tests.helpers import make_settings
from tracker.cli import doctor
from tracker.cli.doctor import examine, merge, repair
from tracker.cli.entries import Context
from tracker.core.models import Projects, new_project


def context(tmp_path: Path, data: Projects, **overrides: object) -> Context:
	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")
	os.environ["TRACKER_ROOTS"] = str(tmp_path / "roots.toml")

	return Context(settings=make_settings(**overrides), data=data, assume_yes=True)


def living(tmp_path: Path, name: str) -> str:
	directory = tmp_path / name
	directory.mkdir(parents=True, exist_ok=True)

	return str(directory)


def test_the_same_project_under_two_entries_is_found(tmp_path: Path):
	here = living(tmp_path, "new-home")

	data: Projects = {
		"/gone/old-home": new_project(
			"/gone/old-home",
			status="dev",
			note="the note worth keeping",
			project_id=3,
			fingerprint="git:abc",
		),
		here: new_project(here, status="unknown", project_id=9, fingerprint="git:abc"),
	}

	report = examine(context(tmp_path, data), deep=False)

	assert len(report.merges) == 1
	assert report.merges[0].gone == "/gone/old-home"
	assert report.merges[0].here == here
	assert report.merges[0].reason == "fingerprint"


def test_repairing_keeps_the_old_history_and_the_living_path(tmp_path: Path):
	here = living(tmp_path, "new-home")

	data: Projects = {
		"/gone/old-home": new_project(
			"/gone/old-home",
			status="dev",
			note="the note worth keeping",
			project_id=3,
			fingerprint="git:abc",
		),
		here: new_project(here, status="unknown", project_id=9, fingerprint="git:abc"),
	}

	data["/gone/old-home"]["uses"] = 4
	data[here]["uses"] = 2

	holder = context(tmp_path, data)

	_ = repair(holder, examine(holder, deep=False), stale=False)

	assert list(data) == [here]
	assert data[here]["id"] == 3
	assert data[here]["status"] == "dev"
	assert data[here].get("note") == "the note worth keeping"
	assert data[here].get("uses") == 6


def test_neither_note_is_thrown_away():
	old = new_project("/gone/x", status="dev", note="older", project_id=1)
	new = new_project("/here/x", status="stable", note="newer", project_id=2)

	merge(old, new, make_settings())

	assert new.get("note") == "older | newer"


def test_a_default_status_never_overwrites_a_real_one():
	old = new_project("/gone/x", status="unknown", project_id=1)
	new = new_project("/here/x", status="stable", project_id=2)

	merge(old, new, make_settings())

	assert new["status"] == "stable"


def test_two_projects_sharing_a_name_are_left_alone(tmp_path: Path):
	first = living(tmp_path, "alpha")
	second = living(tmp_path, "nested/alpha")

	data: Projects = {
		"/gone/alpha": new_project("/gone/alpha", status="dev", project_id=1),
		first: new_project(first, status="unknown", project_id=2),
		second: new_project(second, status="unknown", project_id=3),
	}

	report = examine(context(tmp_path, data), deep=False)

	assert not report.merges


def test_a_project_found_somewhere_else_is_repointed(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
	watched = tmp_path / "watched"
	here = living(tmp_path, "watched/moved-here")

	(Path(here) / ".git").mkdir()

	def marked(path: str) -> str:
		del path

		return "git:abc"

	monkeypatch.setattr(doctor, "fingerprint_of", marked)

	data: Projects = {
		"/gone/old-home": new_project(
			"/gone/old-home", status="dev", project_id=3, fingerprint="git:abc"
		)
	}

	holder = context(tmp_path, data, daemon__paths=[str(watched)])

	report = examine(holder)

	assert len(report.moves) == 1
	assert report.moves[0].found == here

	_ = repair(holder, report, stale=False)

	assert list(data) == [here]
	assert data[here]["id"] == 3


def test_what_cannot_be_placed_anywhere_is_only_reported(tmp_path: Path):
	data: Projects = {"/gone/lost": new_project("/gone/lost", status="dev", project_id=1)}

	holder = context(tmp_path, data)
	report = examine(holder, deep=False)

	assert report.stale == ["/gone/lost"]

	_ = repair(holder, report, stale=False)

	assert not data["/gone/lost"].get("archived", False)

	_ = repair(holder, report, stale=True)

	assert data["/gone/lost"].get("archived")


def test_a_living_project_without_marks_is_reported(tmp_path: Path):
	here = living(tmp_path, "unmarked")

	data: Projects = {here: new_project(here, status="dev", project_id=1)}

	report = examine(context(tmp_path, data), deep=False)

	assert report.unmarked == [here]


def test_a_path_no_other_machine_could_place_is_reported(tmp_path: Path):
	data: Projects = {
		"/srv/work/alpha": new_project("/srv/work/alpha", status="dev", project_id=1)
	}

	report = examine(context(tmp_path, data), deep=False)

	assert report.private == ["/srv/work/alpha"]


def test_a_healthy_database_reports_nothing(tmp_path: Path):
	here = living(tmp_path, "fine")

	data: Projects = {
		here: new_project(
			here,
			status="dev",
			project_id=1,
			identity="thismachine:1:2",
			fingerprint="git:abc",
		)
	}

	from tracker.core.identity import machine_id

	data[here]["identity"] = f"{machine_id()}:1:2"

	report = examine(context(tmp_path, data), deep=False)

	assert report.total == 0
