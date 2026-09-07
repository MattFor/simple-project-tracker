import tomllib
from pathlib import Path

from tests.helpers import make_settings
from tracker.config.defaults import defaults
from tracker.config.settings import Settings, coerce, parse_setting_value
from tracker.config.writer import serialise, write_setting


def test_partial_configuration_falls_back_to_defaults():
	settings = Settings.merged({"display": {"list_limit": 3}})

	assert settings["display"]["list_limit"] == 3
	assert settings["display"]["note_position"] == "auto"
	assert settings["sorting"]["by"] == defaults()["sorting"]["by"]


def test_empty_configuration_is_complete():
	settings = Settings.merged({})

	for key, _ in defaults().items():
		assert key in settings.raw


def test_unknown_keys_are_reported():
	settings = Settings.merged({"display": {"nonsense": 1}})

	assert any("nonsense" in problem for problem in settings.problems)


def test_override_rejects_the_wrong_type():
	settings = make_settings()

	try:
		_ = settings.override("display.list_limit", "abc")
	except ValueError:
		pass
	else:
		raise AssertionError("a non numeric limit should be rejected")


def test_override_rejects_unknown_settings():
	settings = make_settings()

	try:
		_ = settings.override("display.nope", 1)
	except KeyError:
		pass
	else:
		raise AssertionError("an unknown setting should be rejected")


def test_override_limits_choices():
	settings = make_settings()

	assert settings.override("sorting.by", "name")["sorting"]["by"] == "name"

	try:
		_ = settings.override("sorting.by", "sideways")
	except ValueError:
		pass
	else:
		raise AssertionError("an unknown sort key should be rejected")


def test_coerce_accepts_comma_separated_lists():
	assert coerce("display.columns", "id,name", ["a"]) == ["id", "name"]


def test_parse_setting_value_uses_toml_rules():
	assert parse_setting_value("true") is True
	assert parse_setting_value("12") == 12
	assert parse_setting_value("plain") == "plain"


def test_writer_keeps_comments(tmp_path: Path):
	path = tmp_path / "settings.toml"
	_ = path.write_text("[display]\n# keep me\nlist_limit = 20\n")

	assert write_setting(path, "display.list_limit", 42) is None

	text = path.read_text()

	assert "# keep me" in text
	assert tomllib.loads(text)["display"]["list_limit"] == 42


def test_writer_adds_missing_keys_and_sections(tmp_path: Path):
	path = tmp_path / "settings.toml"
	_ = path.write_text("[display]\nlist_limit = 20\n")

	assert write_setting(path, "display.show_notes", False) is None
	assert write_setting(path, "daemon.interval", 30) is None

	data = tomllib.loads(path.read_text())

	assert data["display"]["show_notes"] is False
	assert data["daemon"]["interval"] == 30


def test_writer_replaces_multi_line_arrays(tmp_path: Path):
	path = tmp_path / "settings.toml"
	_ = path.write_text(
		'[projects]\nignore = [\n    ".git",\n    "venv"\n]\n\n[output]\ncolour = true\n'
	)

	assert write_setting(path, "projects.ignore", [".git"]) is None

	data = tomllib.loads(path.read_text())

	assert data["projects"]["ignore"] == [".git"]
	assert data["output"]["colour"] is True


def test_serialise_round_trips():
	assert serialise(True) == "true"
	assert serialise(7) == "7"
	assert serialise(["a", "b"]) == '["a", "b"]'
	assert serialise('say "hi"') == '"say \\"hi\\""'


def test_new_settings_are_known_and_validated():
	from tracker.config.settings import Settings

	settings = Settings.merged({})

	assert settings.get("display.relative_style") == "long"
	assert settings.get("sorting.status_order") == []
	assert settings.get("projects.number_preference") == "ask"
	assert settings.get("projects.track_usage") is True

	assert (
		settings.override("display.relative_style", "short").get("display.relative_style")
		== "short"
	)

	assert settings.override("sorting.by", "last_used").get("sorting.by") == "last_used"

	for key, value in (
		("display.relative_style", "medium"),
		("projects.number_preference", "maybe"),
		("sorting.by", "colour"),
	):
		try:
			_ = settings.override(key, value)
		except ValueError:
			continue

		raise AssertionError(f"{key} accepted {value}")


def test_a_section_display_wins_over_the_shared_one():
	settings = make_settings(
		display__show_headers=False,
		todos__display__show_headers=True,
	)

	todos = settings.scoped("todos")

	assert todos["display"]["show_headers"] is True

	assert todos["display"]["note_position"] == settings["display"]["note_position"]

	assert settings["display"]["show_headers"] is False


def test_a_section_without_a_display_changes_nothing():
	settings = make_settings(display__show_headers=False)

	assert settings.scoped("todos")["display"]["show_headers"] is False


def test_a_scoped_status_colour_sits_over_the_shared_table():
	from tracker.ui.render import status_colour

	settings = make_settings(todos__display__status_colours={"done": "gray"})
	todos = settings.scoped("todos")

	assert status_colour("done", todos) == "gray"
	assert status_colour("todo", todos) == "yellow"

	assert status_colour("done", settings) == "cyan"


def test_a_scoped_key_is_typed_like_the_one_it_mirrors():
	settings = make_settings()

	limited = settings.override("todos.display.list_limit", "5")

	assert limited.get("todos.display.list_limit") == 5

	for key, value in (
		("todos.display.list_limit", "abc"),
		("todos.display.name_style", "sideways"),
	):
		try:
			_ = settings.override(key, value)
		except ValueError:
			continue

		raise AssertionError(f"{key} accepted {value}")


def test_a_scoped_table_is_written_to_a_section_of_its_own(tmp_path: Path):
	path = tmp_path / "settings.toml"

	_ = path.write_text('[todos]\nsort = "id"\n')

	assert write_setting(path, "todos.display.columns", ["tid", "name"]) is None

	data = tomllib.loads(path.read_text())

	assert data["todos"]["display"]["columns"] == ["tid", "name"]
	assert data["todos"]["sort"] == "id"


def test_the_shipped_file_and_the_defaults_agree():
	from tracker.config import paths

	shipped = tomllib.loads(
		paths.bundled_file(paths.SETTINGS_NAME).read_text(encoding="utf-8")
	)

	reference = defaults()

	example = {("daemon", "paths")}

	for section, values in reference.items():
		assert section in shipped, f"[{section}] is missing from settings.toml"

		for key, value in values.items():
			assert key in shipped[section], f"{section}.{key} is missing"

			if (section, key) in example:
				continue

			assert shipped[section][key] == value, f"{section}.{key} disagrees"

	for section, values in shipped.items():
		assert section in reference, f"[{section}] is not a known section"

		for key in values:
			assert key in reference[section], f"{section}.{key} is not a known setting"


def test_every_setting_can_be_overridden_from_the_command_line():
	settings = make_settings()

	for key, value in settings.items():
		if isinstance(value, dict):
			continue

		assert settings.override(key, value).get(key) == value


def test_a_table_is_never_written_back_as_one_line(tmp_path: Path):
	path = tmp_path / "settings.toml"

	_ = path.write_text(
		"[projects]\nauto_status = false\n\n[projects.auto_status_rules]\ndev = 7\n"
	)

	before = path.read_text()
	error = write_setting(path, "projects.auto_status_rules", {"dev": 1})

	assert error is not None and "settings edit" in error
	assert path.read_text() == before
	assert tomllib.loads(path.read_text())["projects"]["auto_status_rules"] == {"dev": 7}


def test_a_list_is_still_written(tmp_path: Path):
	path = tmp_path / "settings.toml"

	_ = path.write_text("[display]\nfilter = []\n\n[display.status_colours]\ndev = 1\n")

	assert write_setting(path, "display.filter", ["-s:archive"]) is None

	data = tomllib.loads(path.read_text())

	assert data["display"]["filter"] == ["-s:archive"]
	assert data["display"]["status_colours"] == {"dev": 1}
