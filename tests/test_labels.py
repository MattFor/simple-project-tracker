from datetime import datetime, timedelta
from pathlib import Path

from tests.helpers import make_projects, make_settings
from tracker.core.discovery import find_projects, get_last_touched_date
from tracker.core.labels import apply_labels, label_of, rules

NOW = datetime(2026, 8, 23, 12, 0, 0)


def aged(*days: float):
	return make_projects(
		*(
			(
				f"/code/project{index}",
				"unknown",
				(NOW - timedelta(days=age)).strftime("%Y-%m-%d %H:%M:%S"),
				"",
			)
			for index, age in enumerate(days, 1)
		)
	)


def test_rules_are_read_youngest_first():
	settings = make_settings()

	assert [status for _, status in rules(settings)] == ["dev", "stable", "archive"]
	assert rules(settings)[-1][0] == float("inf")


def test_a_label_follows_the_age_of_the_project():
	settings = make_settings()

	projects = aged(1, 30, 400)
	labels = [label_of(project, settings, NOW) for project in projects.values()]

	assert labels == ["dev", "stable", "archive"]


def test_an_unknown_timestamp_lands_in_the_oldest_bucket():
	projects = make_projects(("/code/a", "unknown", "unknown", ""))
	settings = make_settings()

	assert label_of(projects["/code/a"], settings, NOW) == "archive"


def test_labels_are_only_applied_when_they_are_turned_on():
	projects = aged(1)
	settings = make_settings()

	assert apply_labels(projects, settings, NOW) == []
	assert projects["/code/project1"]["status"] == "unknown"

	changes = apply_labels(projects, make_settings(projects__auto_status=True), NOW)

	assert changes == [("/code/project1", "unknown", "dev")]
	assert projects["/code/project1"]["status"] == "dev"


def test_a_status_set_by_hand_is_never_rewritten():
	projects = aged(1, 1)

	projects["/code/project1"]["status"] = "blocked"

	settings = make_settings(projects__auto_status=True)

	changes = apply_labels(projects, settings, NOW)

	assert [path for path, _, _ in changes] == ["/code/project2"]
	assert projects["/code/project1"]["status"] == "blocked"


def test_an_automatic_status_ages_into_the_next_one():
	projects = aged(200)

	projects["/code/project1"]["status"] = "dev"

	settings = make_settings(projects__auto_status=True)

	assert apply_labels(projects, settings, NOW) == [("/code/project1", "dev", "archive")]


def test_the_rules_can_be_replaced():
	projects = aged(3)

	settings = make_settings(
		projects__auto_status=True,
		projects__auto_status_rules={"hot": 1, "cold": 0},
	)

	assert apply_labels(projects, settings, NOW) == [
		("/code/project1", "unknown", "cold")
	]


def test_a_new_project_is_labelled_while_it_is_discovered(tmp_path: Path):
	(tmp_path / "alpha" / ".git").mkdir(parents=True)
	_ = (tmp_path / "alpha" / "main.py").write_text("print()\n")

	found = find_projects(str(tmp_path), make_settings(projects__auto_status=True))

	assert found[str(tmp_path / "alpha")]["status"] == "dev"


def test_generated_files_do_not_count_as_work(tmp_path: Path):
	source = tmp_path / "main.py"
	_ = source.write_text("print()\n")

	import os

	os.utime(source, (1_000_000, 1_000_000))

	_ = (tmp_path / "data.pkl").write_bytes(b"x")

	counted = get_last_touched_date(str(tmp_path))
	skipped = get_last_touched_date(str(tmp_path), (), False, ["*.pkl"])

	assert counted is not None and skipped is not None
	assert skipped < counted
	assert skipped == datetime.fromtimestamp(1_000_000)


def test_an_ignored_file_pattern_reaches_a_scan(tmp_path: Path):
	import os

	project = tmp_path / "alpha"
	(project / ".git").mkdir(parents=True)

	_ = (project / "main.py").write_text("print()\n")
	os.utime(project / "main.py", (1_000_000, 1_000_000))
	os.utime(project / ".git", (1_000_000, 1_000_000))
	os.utime(project, (1_000_000, 1_000_000))

	_ = (project / "state.db").write_bytes(b"x")

	settings = make_settings(projects__ignore_files=["*.db"])

	found = find_projects(str(tmp_path), settings)

	assert found[str(project)]["last_touched"] == datetime.fromtimestamp(
		1_000_000
	).strftime("%Y-%m-%d %H:%M:%S")
