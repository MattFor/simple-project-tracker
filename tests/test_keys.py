from tracker.config.settings import Settings
from tracker.config.keys import known_keys, resolve_key


def resolved(query: str) -> str | None:
	return resolve_key(query)[0]


def test_every_setting_is_reachable_by_its_full_name():
	for key in known_keys():
		assert resolved(key) == key


def test_every_setting_has_a_unique_bare_name():
	for key in known_keys():
		assert resolved(key.split(".")[-1]) == key


def test_a_name_can_be_shortened_in_several_ways():
	for query in ("display.list_limit", "list_limit", "list_lim", "l_l", "ll"):
		assert resolved(query) == "display.list_limit"

	assert resolved("crp") == "projects.conflict_resolution_preference"
	assert resolved("auto_status") == "projects.auto_status"
	assert resolved("asr") == "projects.auto_status_rules"


def test_the_section_shortens_the_same_way():
	assert resolved("d.ll") == "display.list_limit"
	assert resolved("dis.list_lim") == "display.list_limit"
	assert resolved("d.i") == "daemon.interval"
	assert resolved("display.list_limit") == "display.list_limit"


def test_a_section_keeps_two_settings_apart():
	assert resolved("interval") == "daemon.interval"
	assert resolved("p.ignore") == "projects.ignore"
	assert resolved("s.exclude") == "scan.exclude"


def test_an_ambiguous_name_reports_what_it_could_mean():
	found, candidates = resolve_key("nmw")

	assert found is None
	assert candidates == ["display.name_max_width", "display.note_min_width"]

	found, candidates = resolve_key("p.i")

	assert found is None
	assert candidates == ["projects.ignore", "projects.ignore_files"]


def test_an_unknown_name_matches_nothing():
	for query in ("", "nonsense", "display.nonsense", "zzz"):
		assert resolve_key(query) == (None, [])


def test_an_exact_name_wins_over_a_looser_match():
	# "filter" is a setting of its own, never the start of another
	assert resolved("filter") == "display.filter"
	assert resolved("format") == "display.format"
	assert resolved("by") == "sorting.by"


def test_a_resolved_name_can_be_overridden():
	settings = Settings.merged({})

	for query in ("ll", "d.ll", "list_limit"):
		key = resolved(query)

		assert key is not None
		assert settings.override(key, 7).get(key) == 7


def test_a_nested_table_entry_is_left_alone():
	assert resolved("display.status_colours.dev") == "display.status_colours.dev"
