import os
from pathlib import Path

from tests.helpers import make_settings
from tracker.core import portable
from tracker.core.discovery import find_projects
from tracker.core.models import new_project
from tracker.core.storage import load_data, save_data
from tracker.util.files import load_pkl, save_pkl


def with_roots(path: Path, **named: str) -> None:
	lines = [f'{name} = "{value}"' for name, value in named.items()]

	_ = path.write_text("[roots]\n" + "\n".join(lines), encoding="utf-8")

	os.environ["TRACKER_ROOTS"] = str(path)


def only_home(tmp_path: Path) -> None:
	with_roots(tmp_path / "roots.toml")


def test_a_path_under_home_travels_as_home(tmp_path: Path):
	only_home(tmp_path)

	settings = make_settings()
	inside = str(Path.home() / "code" / "alpha")

	assert portable.contract(inside, portable.roots(settings)) == "~/code/alpha"


def test_home_comes_back_as_this_machine_s_home(tmp_path: Path):
	only_home(tmp_path)

	settings = make_settings()

	assert portable.expand("~/code/alpha", portable.roots(settings)) == str(
		Path.home() / "code" / "alpha"
	)


def test_a_named_root_beats_home_when_it_is_more_specific(tmp_path: Path):
	with_roots(tmp_path / "roots.toml", work=str(Path.home() / "code"))

	known = portable.roots(make_settings())
	inside = str(Path.home() / "code" / "alpha")

	assert portable.contract(inside, known) == "@work/alpha"
	assert portable.expand("@work/alpha", known) == inside


def test_a_root_this_machine_never_heard_of_is_kept_as_it_is(tmp_path: Path):
	only_home(tmp_path)

	known = portable.roots(make_settings())

	assert portable.expand("@elsewhere/alpha", known) == "@elsewhere/alpha"
	assert portable.contract("@elsewhere/alpha", known) == "@elsewhere/alpha"


def test_a_path_outside_every_root_stays_absolute(tmp_path: Path):
	only_home(tmp_path)

	known = portable.roots(make_settings())

	assert portable.contract("/srv/work/alpha", known) == "/srv/work/alpha"
	assert not portable.shareable("/srv/work/alpha", known)


def test_the_environment_names_a_root_of_its_own(tmp_path: Path):
	only_home(tmp_path)

	os.environ["TRACKER_ROOT_MEDIA"] = "/archives/media"

	known = portable.roots(make_settings())

	assert portable.contract("/archives/media/photos", known) == "@media/photos"


def test_the_database_is_written_portable_and_read_back_local(tmp_path: Path):
	only_home(tmp_path)

	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")

	settings = make_settings()
	here = str(Path.home() / "code" / "alpha")

	assert save_data({here: new_project(here, status="dev", project_id=1)}, settings)

	stored, _ = load_pkl(tmp_path / "data.pkl")

	assert list(stored) == ["~/code/alpha"]
	assert stored["~/code/alpha"]["path"] == "~/code/alpha"

	assert list(load_data(settings)) == [here]


def test_saving_leaves_the_projects_in_memory_alone(tmp_path: Path):
	only_home(tmp_path)

	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")

	here = str(Path.home() / "code" / "alpha")
	data = {here: new_project(here, status="dev", project_id=1)}

	assert save_data(data, make_settings())

	assert list(data) == [here]
	assert data[here]["path"] == here


def test_turning_it_off_stores_the_absolute_path(tmp_path: Path):
	only_home(tmp_path)

	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")

	settings = make_settings(sync__portable_paths=False)
	here = str(Path.home() / "code" / "alpha")

	assert save_data({here: new_project(here, status="dev", project_id=1)}, settings)

	stored, _ = load_pkl(tmp_path / "data.pkl")

	assert list(stored) == [here]


def test_a_database_written_elsewhere_lands_where_this_machine_keeps_it(
	tmp_path: Path,
):
	with_roots(tmp_path / "roots.toml", work=str(tmp_path / "here"))

	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")

	written = {
		"@work/alpha": new_project(
			"@work/alpha", status="dev", note="shared note", project_id=4
		)
	}

	assert save_pkl(tmp_path / "data.pkl", written)

	loaded = load_data(make_settings())

	assert list(loaded) == [str(tmp_path / "here" / "alpha")]
	assert loaded[str(tmp_path / "here" / "alpha")].get("note") == "shared note"
	assert loaded[str(tmp_path / "here" / "alpha")]["status"] == "dev"


def test_the_other_machine_scans_without_tracking_it_all_a_second_time(
	tmp_path: Path,
):
	here = tmp_path / "code"
	project = here / "alpha"

	(project / ".git").mkdir(parents=True)

	with_roots(tmp_path / "roots.toml", work=str(here))

	os.environ["TRACKER_DATA"] = str(tmp_path / "data.pkl")

	written = {
		"@work/alpha": new_project(
			"@work/alpha",
			status="dev",
			note="written on the other machine",
			project_id=4,
			fingerprint="git:abc",
		)
	}

	assert save_pkl(tmp_path / "data.pkl", written)

	settings = make_settings()
	data = load_data(settings)

	before = set(data)

	_ = find_projects(str(here), settings, data)

	assert set(data) == before
	assert data[str(project)].get("note") == "written on the other machine"
	assert data[str(project)]["status"] == "dev"
	assert data[str(project)]["id"] == 4

	assert save_data(data, settings)

	stored, _ = load_pkl(tmp_path / "data.pkl")

	assert list(stored) == ["@work/alpha"]
