from pathlib import Path

from tests.helpers import Patcher
from tracker.config import paths


def source_tree(root: Path) -> Path:
	package = root / "tracker"
	package.mkdir(parents=True)

	_ = (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

	return package


def pretend_installed(monkeypatch: Patcher, package: Path) -> None:
	monkeypatch.setattr(paths, "_INSTALLED_PACKAGE", package)
	monkeypatch.setattr(paths, "_PACKAGE_INODE", paths._inode(package))
	monkeypatch.setattr(paths, "_recovered", {})


def test_the_package_is_found_again_after_its_directory_is_renamed(
	tmp_path: Path, monkeypatch: Patcher
):
	root = tmp_path / "tracker"
	package = source_tree(root)

	pretend_installed(monkeypatch, package)
	monkeypatch.chdir(root)

	assert paths.package_root() == package
	assert paths.database_dir() == root

	renamed = tmp_path / "simple-project-tracker"
	_ = root.rename(renamed)

	assert paths.package_root() == renamed / "tracker"
	assert paths.project_root() == renamed
	assert paths.in_source_tree()
	assert paths.database_dir() == renamed
	assert paths.share_dir() == renamed / "tracker" / "share"


def test_the_package_is_found_again_from_inside_it(tmp_path: Path, monkeypatch: Patcher):
	root = tmp_path / "tracker"
	package = source_tree(root)

	pretend_installed(monkeypatch, package)
	monkeypatch.chdir(package)

	renamed = tmp_path / "renamed"
	_ = root.rename(renamed)

	assert paths.package_root() == renamed / "tracker"


def test_a_package_that_really_vanished_keeps_the_path_it_was_installed_at(
	tmp_path: Path, monkeypatch: Patcher
):
	root = tmp_path / "tracker"
	package = source_tree(root)

	pretend_installed(monkeypatch, package)
	monkeypatch.chdir(tmp_path)

	# noinspection none-function-assignment
	_ = (root / "pyproject.toml").unlink()
	package.rmdir()
	root.rmdir()

	assert paths.package_root() == package
	assert not paths.in_source_tree()
	assert paths.database_dir() == paths.data_dir()
