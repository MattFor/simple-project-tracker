from pathlib import Path

from tests.helpers import make_settings

from tracker.config.settings import Settings

from tracker.cli.entries import Context
from tracker.core.daemon import merge_scan
from tracker.cli.commands import scan_into
from tracker.core.discovery import find_projects
from tracker.core.models import Projects, new_project
from tracker.core.identity import apply_moves, identity_of


def build(root: Path, *names: str) -> None:
	for name in names:
		(root / name / ".git").mkdir(parents=True)
		_ = (root / name / "main.py").write_text("print()\n")


def scan(root: Path, settings: Settings | None = None) -> Projects:
	return find_projects(str(root), settings or make_settings())


def test_a_checkout_is_identified_by_its_git_directory(tmp_path: Path):
	build(tmp_path, "alpha", "beta")

	alpha = identity_of(str(tmp_path / "alpha"))

	assert alpha
	assert alpha != identity_of(str(tmp_path / "beta"))
	assert identity_of(str(tmp_path / "nothing")) == ""


def test_a_scan_stores_the_identity(tmp_path: Path):
	build(tmp_path, "alpha")

	found = scan(tmp_path)

	assert found[str(tmp_path / "alpha")].get("identity") == identity_of(
		str(tmp_path / "alpha")
	)


def test_a_moved_project_keeps_its_entry(tmp_path: Path):
	watched = tmp_path / "code"
	watched.mkdir()
	build(watched, "alpha")

	settings = make_settings()

	data: Projects = {}
	_ = merge_scan(data, [watched], scan(watched, settings), True, settings)

	old = str(watched / "alpha")

	data[old]["status"] = "dev"
	data[old]["note"] = "keep me"

	kept = data[old]["id"]

	_ = (watched / "alpha").rename(watched / "moved")

	result = merge_scan(data, [watched], scan(watched, settings), True, settings)

	new = str(watched / "moved")

	assert result.moved == [(old, new)]
	assert not result.added and not result.removed
	assert old not in data
	assert data[new]["id"] == kept
	assert data[new]["status"] == "dev"
	assert data[new].get("note") == "keep me"
	assert not data[new].get("archived")


def test_a_project_that_really_vanished_is_still_archived(tmp_path: Path):
	build(tmp_path, "alpha")

	settings = make_settings()

	data: Projects = {}
	_ = merge_scan(data, [tmp_path], scan(tmp_path, settings), True, settings)

	result = merge_scan(data, [tmp_path], {}, True, settings)

	assert not result.moved
	assert result.removed == [str(tmp_path / "alpha")]


def test_move_detection_can_be_turned_off(tmp_path: Path):
	build(tmp_path, "alpha")

	settings = make_settings(scan__detect_moves=False)

	data: Projects = {}
	_ = merge_scan(data, [tmp_path], scan(tmp_path, settings), True, settings)

	_ = (tmp_path / "alpha").rename(tmp_path / "moved")

	result = merge_scan(data, [tmp_path], scan(tmp_path, settings), True, settings)

	assert not result.moved
	assert result.added == [str(tmp_path / "moved")]
	assert result.removed == [str(tmp_path / "alpha")]


def test_an_ambiguous_pair_is_left_alone(tmp_path: Path):
	del tmp_path

	gone = ["/code/old/alpha", "/code/old/beta"]
	arrived = ["/code/new/one", "/code/new/two"]

	data: Projects = {}

	for index, path in enumerate(gone + arrived, 1):
		data[path] = new_project(path, status="dev", project_id=index)
		data[path]["identity"] = "same"

	assert apply_moves(data, arrived, gone) == []
	assert set(data) == set(gone + arrived)


def test_a_name_match_recognises_a_move_without_a_stored_identity(tmp_path: Path):
	old = str(tmp_path / "old" / "alpha")
	new = str(tmp_path / "new" / "alpha")

	data: Projects = {
		old: new_project(old, status="dev", project_id=4, note="mine"),
		new: new_project(new, status="unknown", project_id=9),
	}

	assert apply_moves(data, [new], [old]) == [(old, new)]
	assert data[new]["id"] == 4
	assert data[new].get("note") == "mine"


def test_an_archived_entry_comes_back_when_the_project_reappears(tmp_path: Path):
	build(tmp_path, "alpha")

	settings = make_settings()

	data: Projects = {}
	_ = merge_scan(data, [tmp_path], scan(tmp_path, settings), True, settings)

	old = str(tmp_path / "alpha")

	data[old]["note"] = "important"

	_ = merge_scan(data, [tmp_path], {}, True, settings)

	assert data[old].get("archived") is True

	_ = (tmp_path / "alpha").rename(tmp_path / "moved")

	result = merge_scan(data, [tmp_path], scan(tmp_path, settings), True, settings)

	new = str(tmp_path / "moved")

	assert result.moved == [(old, new)]
	assert data[new].get("note") == "important"
	assert data[new].get("archived") is False


def test_an_unrelated_project_of_the_same_name_is_not_a_move(tmp_path: Path):
	old = str(tmp_path / "old" / "utils")
	new = str(tmp_path / "new" / "utils")

	data: Projects = {
		old: new_project(old, status="archived", project_id=4, note="the old one"),
		new: new_project(new, status="unknown", project_id=9),
	}

	# The vanished one was fingerprinted, so its name alone proves nothing
	data[old]["identity"] = "66306:1"

	assert apply_moves(data, [new], [old]) == []
	assert data[new]["status"] == "unknown"
	assert data[new].get("note", "") == ""
	assert old in data


def test_a_differently_named_arrival_is_not_a_move_without_a_fingerprint(
	tmp_path: Path,
):
	build(tmp_path, "alpha")

	old = str(tmp_path / "beta")
	new = str(tmp_path / "alpha")

	data: Projects = {
		old: new_project(old, status="dev", project_id=4, note="mine"),
		new: scan(tmp_path)[new],
	}

	assert data[new].get("identity")
	assert apply_moves(data, [new], [old]) == []
	assert old in data


def test_a_move_is_followed_when_only_the_new_copy_is_fingerprinted(tmp_path: Path):
	build(tmp_path, "alpha")

	old = str(tmp_path / "elsewhere" / "alpha")
	new = str(tmp_path / "alpha")

	data: Projects = {
		old: new_project(old, status="dev", project_id=4, note="mine"),
		new: scan(tmp_path)[new],
	}

	assert apply_moves(data, [new], [old]) == [(old, new)]
	assert data[new]["id"] == 4
	assert data[new].get("note") == "mine"


def test_a_scan_of_the_new_directory_alone_still_follows_the_rename(tmp_path: Path):
	watched = tmp_path / "code"
	watched.mkdir()
	build(watched, "alpha")

	settings = make_settings()

	data: Projects = {}
	_ = merge_scan(data, [watched], scan(watched, settings), True, settings)

	old = str(watched / "alpha")
	data[old]["note"] = "keep me"

	_ = (watched / "alpha").rename(watched / "renamed")

	new = watched / "renamed"
	holder = Context(settings=settings, data=data)

	result = scan_into(holder, new)

	assert result.moved == [(old, str(new))]
	assert not result.added
	assert old not in data
	assert data[str(new)].get("note") == "keep me"


def test_an_empty_directory_left_behind_does_not_hide_the_move(tmp_path: Path):
	watched = tmp_path / "code"
	watched.mkdir()
	build(watched, "alpha")

	settings = make_settings()

	data: Projects = {}
	_ = merge_scan(data, [watched], scan(watched, settings), True, settings)

	old = str(watched / "alpha")
	data[old]["note"] = "keep me"

	_ = (watched / "alpha").rename(watched / "renamed")

	(watched / "alpha" / ".idea").mkdir(parents=True)

	holder = Context(settings=settings, data=data)
	result = scan_into(holder, watched)

	assert result.moved == [(old, str(watched / "renamed"))]
	assert data[str(watched / "renamed")].get("note") == "keep me"


def test_a_move_carries_the_usage_counter(tmp_path: Path):
	old = str(tmp_path / "old" / "alpha")
	new = str(tmp_path / "new" / "alpha")

	data: Projects = {
		old: new_project(old, status="dev", project_id=4),
		new: new_project(new, status="unknown", project_id=9),
	}

	data[old]["uses"] = 12
	data[old]["last_used"] = "2026-08-01 00:00:00"

	assert apply_moves(data, [new], [old]) == [(old, new)]
	assert data[new].get("uses") == 12
	assert data[new].get("last_used") == "2026-08-01 00:00:00"
