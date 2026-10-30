import io
from contextlib import redirect_stdout
from pathlib import Path

from tests.helpers import make_projects, make_settings
from tracker.config.metadata import Metadata
from tracker.core.models import Project, archive
from tracker.ui.details import print_details


def shown(path: str, project: Project, **overrides: object) -> str:
	stream = io.StringIO()

	with redirect_stdout(stream):
		print_details(path, project, make_settings(**overrides), 3)

	return stream.getvalue()


def sample(path: str = "/code/alpha") -> Project:
	projects = make_projects((path, "dev", "2026-01-05 10:00:00", "the note"))

	return projects[path]


def test_the_sections_of_a_project_that_is_gone():
	text = shown("/code/alpha", sample())

	assert "Tracking" in text
	assert "TID             3" in text
	assert "Status          dev" in text
	assert "Exists          no" in text
	assert "the note" in text

	assert "Size" not in text


def test_a_project_on_disk_is_measured(tmp_path: Path):
	project = tmp_path / "alpha"
	(project / ".git").mkdir(parents=True)

	_ = (project / "main.py").write_text("print()\n")

	text = shown(str(project), sample(str(project)))

	assert "Exists          yes" in text
	assert "Size" in text
	assert "Files           1" in text
	assert "Language        Python" in text


def test_a_note_may_colour_itself():
	project = sample()
	project["note"] = "{red}broken{/} since friday"

	assert "broken since friday" in shown("/code/alpha", project)
	assert "{red}" not in shown("/code/alpha", project)


def test_an_archived_project_shows_what_it_was():
	project = sample()

	archive(project, "2026-02-01 00:00:00")

	text = shown("/code/alpha", project)

	assert "Archived        yes" in text
	assert "Deleted at" in text
	assert "Note before archiving" in text
	assert "the note" in text


def test_uses_are_only_shown_once_there_are_any():
	project = sample()

	assert "Uses" not in shown("/code/alpha", project)

	project["uses"] = 4

	assert "Uses            4" in shown("/code/alpha", project)


def test_verbose_adds_the_stored_fields():
	project = sample()
	project["identity"] = "66306:1"

	stream = io.StringIO()

	with redirect_stdout(stream):
		print_details("/code/alpha", project, make_settings(), 1, verbose=True)

	text = stream.getvalue()

	assert "Stored fields" in text
	assert "66306:1" in text
	assert "Checked at" in text


def test_the_metadata_falls_back_to_the_source_tree():
	project = Metadata()

	assert project.name
	assert project.version
	assert project.author


def test_every_branch_is_listed_only_when_asked_for(tmp_path: Path):
	import shutil
	import subprocess

	import pytest

	if not shutil.which("git"):
		pytest.skip("no git")

	def git(*args: str) -> None:
		_ = subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

	git("init", "-q", "-b", "main")
	git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "first")
	git("branch", "side")
	git("update-ref", "refs/remotes/origin/main", "HEAD")
	git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

	local = shown(str(tmp_path), sample(str(tmp_path)), output__branches="local")
	every = shown(str(tmp_path), sample(str(tmp_path)), output__branches="all")

	assert "* main" in local and "  side" in local
	assert "origin/main" not in local
	assert "origin/main" in every
	# origin/HEAD only points at origin/main
	assert "  origin " not in every
	assert "Branches" not in shown(str(tmp_path), sample(str(tmp_path)))
