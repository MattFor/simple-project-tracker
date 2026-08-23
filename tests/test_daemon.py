from pathlib import Path

from tests.helpers import make_settings

from tracker.core.daemon import merge_scan
from tracker.core.discovery import find_projects
from tracker.core.models import Projects, new_project


def build(root: Path, *names: str) -> None:
	for name in names:
		(root / name / ".git").mkdir(parents=True)
		_ = (root / name / "main.py").write_text("print()\n")


def test_a_scan_refreshes_timestamps_without_touching_edits(tmp_path: Path):
	build(tmp_path, "alpha")

	settings = make_settings()

	found = find_projects(str(tmp_path), settings)

	data: Projects = {}

	_ = merge_scan(data, [tmp_path], found, True, settings)

	alpha = str(tmp_path / "alpha")

	data[alpha]["status"] = "shelf"
	data[alpha]["note"] = "mine"

	changed, added, removed = merge_scan(data, [tmp_path], found, True, settings)

	assert not added and not removed
	assert not changed
	assert data[alpha]["status"] == "shelf"
	assert data[alpha].get("note") == "mine"


def test_a_scan_never_resurrects_what_the_database_no_longer_has(tmp_path: Path):
	build(tmp_path, "alpha")

	settings = make_settings()
	found = find_projects(str(tmp_path), settings)

	data: Projects = {}
	_ = merge_scan(data, [tmp_path], found, True, settings)

	alpha = str(tmp_path / "alpha")

	data[alpha]["note"] = "written before the removal"

	del data[alpha]

	_, added, _ = merge_scan(data, [tmp_path], found, True, settings)

	assert added == [alpha]
	assert data[alpha].get("note", "") == ""


def test_a_vanished_project_is_archived_once(tmp_path: Path):
	build(tmp_path, "alpha")

	settings = make_settings()
	found = find_projects(str(tmp_path), settings)

	data: Projects = {}
	_ = merge_scan(data, [tmp_path], found, True, settings)

	changed, _, removed = merge_scan(data, [tmp_path], {}, True, settings)

	alpha = str(tmp_path / "alpha")

	assert changed
	assert removed == [alpha]
	assert data[alpha].get("archived") is True

	changed, _, removed = merge_scan(data, [tmp_path], {}, True, settings)

	assert not removed
	assert not changed


def test_an_excluded_project_is_left_alone_by_the_daemon(tmp_path: Path):
	settings = make_settings(scan__exclude=[str(tmp_path / "alpha")])

	alpha = str(tmp_path / "alpha")

	data: Projects = {alpha: new_project(alpha, status="shelf", project_id=1)}

	changed, added, removed = merge_scan(data, [tmp_path], {}, True, settings)

	assert not changed and not added and not removed
	assert alpha in data
