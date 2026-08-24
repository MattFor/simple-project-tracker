import io

from pathlib import Path
from contextlib import redirect_stdout

from tests.helpers import make_projects, make_settings

from tracker.ui.details import print_details
from tracker.config.metadata import Metadata
from tracker.core.models import Project, archive


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
