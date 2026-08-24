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

	result = merge_scan(data, [tmp_path], found, True, settings)

	assert not result.added and not result.removed
	assert not result.changed
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

	result = merge_scan(data, [tmp_path], found, True, settings)

	assert result.added == [alpha]
	assert data[alpha].get("note", "") == ""


def test_a_vanished_project_is_archived_once(tmp_path: Path):
	build(tmp_path, "alpha")

	settings = make_settings()
	found = find_projects(str(tmp_path), settings)

	data: Projects = {}
	_ = merge_scan(data, [tmp_path], found, True, settings)

	result = merge_scan(data, [tmp_path], {}, True, settings)

	alpha = str(tmp_path / "alpha")

	assert result.changed
	assert result.removed == [alpha]
	assert data[alpha].get("archived") is True

	result = merge_scan(data, [tmp_path], {}, True, settings)

	assert not result.removed
	assert not result.changed


def test_an_excluded_project_is_left_alone_by_the_daemon(tmp_path: Path):
	settings = make_settings(scan__exclude=[str(tmp_path / "alpha")])

	alpha = str(tmp_path / "alpha")

	data: Projects = {alpha: new_project(alpha, status="shelf", project_id=1)}

	result = merge_scan(data, [tmp_path], {}, True, settings)

	assert not result.changed and not result.added and not result.removed
	assert alpha in data


def test_a_scan_labels_only_what_it_scanned(tmp_path: Path):
	build(tmp_path, "alpha")

	settings = make_settings(projects__auto_status=True)

	outside = "/code/outside"

	data: Projects = {outside: new_project(outside, status="unknown", project_id=9)}

	_ = merge_scan(
		data, [tmp_path], find_projects(str(tmp_path), settings), True, settings
	)

	alpha = str(tmp_path / "alpha")

	assert data[alpha]["status"] == "dev"
	assert data[outside]["status"] == "unknown"


def test_the_stray_hunt_only_looks_at_this_user():
	import os
	import subprocess

	from tracker.core.daemon import find_stray_daemons

	calls: list[list[str]] = []

	original = subprocess.run

	def record(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
		calls.append(command)

		return original(["true"], capture_output=True, text=True, check=False)

	subprocess.run = record

	try:
		_ = find_stray_daemons()
	finally:
		subprocess.run = original

	assert calls and calls[0][:3] == ["pgrep", "-u", str(os.getuid())]
