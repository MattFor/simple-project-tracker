from pathlib import Path

import pytest

from tracker.core import identity
from tracker.core.identity import (
	apply_moves,
	detect_moves,
	is_local,
	machine_id,
	mark,
	needs_marking,
	split_identity,
	vanished,
)
from tracker.core.models import Projects, new_project


def elsewhere() -> str:
	return "someothermachine:66306:1234"


def test_an_identity_says_which_machine_read_it():
	machine, inode = split_identity(f"{machine_id()}:66306:1234")

	assert machine == machine_id()
	assert inode == "66306:1234"

	assert is_local(f"{machine_id()}:66306:1234")
	assert not is_local(elsewhere())


def test_an_identity_from_before_the_machine_was_recorded_is_this_one():
	machine, inode = split_identity("66306:1234")

	assert machine == ""
	assert inode == "66306:1234"

	assert is_local("66306:1234")


def test_a_directory_that_is_there_has_not_vanished(tmp_path: Path):
	project = new_project(str(tmp_path), status="dev", project_id=1)

	assert not vanished(str(tmp_path), project)


def test_another_machine_s_inode_never_condemns_a_directory(tmp_path: Path):
	project = new_project(str(tmp_path), status="dev", project_id=1, identity=elsewhere())

	# The inode belongs to a machine that is not this one
	assert not vanished(str(tmp_path), project)


def test_a_directory_that_is_not_there_has_vanished():
	project = new_project("/gone/alpha", status="dev", project_id=1)

	assert vanished("/gone/alpha", project)


def test_a_move_is_followed_by_the_fingerprint(tmp_path: Path):
	old = "/gone/old-home"
	new = str(tmp_path / "new-home")

	data: Projects = {
		old: new_project(
			old, status="dev", note="kept", project_id=3, fingerprint="git:abc"
		),
		new: new_project(new, status="unknown", project_id=9, fingerprint="git:abc"),
	}

	assert detect_moves(data, [new], [old]) == {old: new}

	moved = apply_moves(data, [new], [old])

	assert moved == [(old, new)]
	assert list(data) == [new]
	assert data[new]["id"] == 3
	assert data[new]["status"] == "dev"
	assert data[new].get("note") == "kept"


def test_a_fingerprint_beats_a_shared_name(tmp_path: Path):
	old = "/gone/alpha"
	right = str(tmp_path / "right" / "alpha")
	wrong = str(tmp_path / "wrong" / "alpha")

	data: Projects = {
		old: new_project(old, status="dev", project_id=1, fingerprint="git:abc"),
		right: new_project(right, status="unknown", project_id=2, fingerprint="git:abc"),
		wrong: new_project(wrong, status="unknown", project_id=3, fingerprint="git:xyz"),
	}

	assert detect_moves(data, [right, wrong], [old]) == {old: right}


def test_an_inode_from_another_machine_pairs_with_nothing(tmp_path: Path):
	old = "/gone/alpha"
	new = str(tmp_path / "beta")

	data: Projects = {
		old: new_project(old, status="dev", project_id=1, identity=elsewhere()),
		new: new_project(new, status="unknown", project_id=2, identity=elsewhere()),
	}

	assert detect_moves(data, [new], [old]) == {}


def test_an_inode_recorded_before_machines_had_names_is_restamped(tmp_path: Path):
	(tmp_path / ".git").mkdir()

	project = new_project(
		str(tmp_path), status="dev", project_id=1, identity="66306:1234"
	)

	assert needs_marking(project)
	assert mark(str(tmp_path), project)
	assert str(project.get("identity", "")).startswith(f"{machine_id()}:")


def test_this_machine_restamps_an_inode_of_its_own_that_moved_on(tmp_path: Path):
	(tmp_path / ".git").mkdir()

	project = new_project(
		str(tmp_path),
		status="dev",
		project_id=1,
		identity=f"{machine_id()}:1:2",
		fingerprint="git:abc",
	)

	assert mark(str(tmp_path), project)
	assert project.get("identity") != f"{machine_id()}:1:2"

	assert not mark(str(tmp_path), project)


def test_another_machine_s_inode_is_left_where_it_is(tmp_path: Path):
	(tmp_path / ".git").mkdir()

	project = new_project(
		str(tmp_path),
		status="dev",
		project_id=1,
		identity=elsewhere(),
		fingerprint="git:abc",
	)

	assert not needs_marking(project)

	_ = mark(str(tmp_path), project)

	assert project.get("identity") == elsewhere()


def test_a_matching_fingerprint_outvotes_an_inode_that_disagrees(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
	(tmp_path / ".git").mkdir()

	def same(path: str) -> str:
		del path

		return "git:abc"

	monkeypatch.setattr(identity, "fingerprint_of", same)

	project = new_project(
		str(tmp_path),
		status="dev",
		project_id=1,
		identity=f"{machine_id()}:1:2",
		fingerprint="git:abc",
	)

	assert not vanished(str(tmp_path), project)


def test_a_different_repository_at_the_same_path_has_vanished(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
	(tmp_path / ".git").mkdir()

	def other(path: str) -> str:
		del path

		return "git:something-else"

	monkeypatch.setattr(identity, "fingerprint_of", other)

	project = new_project(
		str(tmp_path),
		status="dev",
		project_id=1,
		identity=f"{machine_id()}:1:2",
		fingerprint="git:abc",
	)

	assert vanished(str(tmp_path), project)
