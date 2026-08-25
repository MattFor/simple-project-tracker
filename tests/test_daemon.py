from pathlib import Path

from tests.helpers import make_settings

from tracker.core.daemon import merge_scan
from tracker.core.discovery import find_projects
from tracker.core.models import Projects, archive, new_project


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


#
# An umbrella repository must not override the scan
#


def test_a_repository_at_the_scan_root_does_not_hide_what_is_under_it(tmp_path: Path):
	build(tmp_path, "alpha", "beta")

	settings = make_settings(scan__stop_at_project=True)

	assert len(find_projects(str(tmp_path), settings)) == 2

	(tmp_path / ".git").mkdir()

	found = find_projects(str(tmp_path), settings)

	assert str(tmp_path / "alpha") in found
	assert str(tmp_path / "beta") in found


def test_stopping_at_a_project_still_skips_a_repository_nested_inside_one(
	tmp_path: Path,
):
	build(tmp_path, "alpha")

	(tmp_path / "alpha" / "lib" / "vendored" / ".git").mkdir(parents=True)
	(tmp_path / ".git").mkdir()

	found = find_projects(str(tmp_path), make_settings(scan__stop_at_project=True))

	assert str(tmp_path / "alpha") in found
	assert str(tmp_path / "alpha" / "lib" / "vendored") not in found


def test_a_rescan_restores_a_project_that_was_wrongly_marked_deleted(tmp_path: Path):
	build(tmp_path, "alpha")

	settings = make_settings()
	data = find_projects(str(tmp_path), settings)

	alpha = str(tmp_path / "alpha")

	data[alpha]["note"] = "mine"
	archive(data[alpha], "2026-08-24 18:21:30")

	assert data[alpha]["archived"]

	_ = find_projects(str(tmp_path), settings, data)

	assert not data[alpha]["archived"]
	assert data[alpha]["note"] == "mine"


#
# The brake on a scan that loses everything at once
#


def test_a_scan_that_loses_almost_everything_is_refused(tmp_path: Path):
	names = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")

	build(tmp_path, *names)

	settings = make_settings()
	found = find_projects(str(tmp_path), settings)

	data: Projects = {}
	_ = merge_scan(data, [tmp_path], found, True, settings)

	result = merge_scan(data, [tmp_path], {}, True, settings)

	assert result.removed == []
	assert len(result.blocked) == len(names)
	assert not any(project.get("archived", False) for project in data.values())
	assert all("[DELETED]" not in project.get("note", "") for project in data.values())


def test_losing_a_believable_share_of_the_projects_still_archives_them(tmp_path: Path):
	names = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta")

	build(tmp_path, *names)

	settings = make_settings()
	found = find_projects(str(tmp_path), settings)

	data: Projects = {}
	_ = merge_scan(data, [tmp_path], found, True, settings)

	survivors = [str(tmp_path / name) for name in names[:5]]
	kept = {path: found[path] for path in survivors}

	result = merge_scan(data, [tmp_path], kept, True, settings)

	assert len(result.removed) == 3
	assert not result.blocked
	assert not data[survivors[0]].get("archived", False)
	assert data[str(tmp_path / names[-1])]["archived"]


def test_a_single_deletion_is_never_blocked_however_small_the_database(
	tmp_path: Path,
):
	build(tmp_path, "alpha", "beta")

	settings = make_settings()
	found = find_projects(str(tmp_path), settings)

	data: Projects = {}
	_ = merge_scan(data, [tmp_path], found, True, settings)

	alpha = str(tmp_path / "alpha")
	result = merge_scan(data, [tmp_path], {alpha: found[alpha]}, True, settings)

	assert result.removed == [str(tmp_path / "beta")]
	assert not result.blocked


def test_the_brake_can_be_lifted(tmp_path: Path):
	build(tmp_path, "alpha", "beta", "gamma", "delta")

	settings = make_settings(scan__vanish_limit=100)
	found = find_projects(str(tmp_path), settings)

	data: Projects = {}
	_ = merge_scan(data, [tmp_path], found, True, settings)

	result = merge_scan(data, [tmp_path], {}, True, settings)

	assert len(result.removed) == 4
	assert not result.blocked
