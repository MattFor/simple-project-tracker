from tracker.config import paths
from tracker.ui.help import dedent, find, keys, parse


def blocks():
	return parse(paths.help_file().read_text(encoding="utf-8"))


def test_every_command_has_its_own_section():
	from tracker.cli.app import HANDLERS

	commands, _ = keys(blocks())

	missing = [name for name in HANDLERS if name != "show" and name not in commands]

	assert not missing, f"no help section for {missing}"


def test_a_command_is_found_through_any_of_its_aliases():
	found = blocks()

	for alias in ("list", "l", "ls", "--list"):
		lines = find(found, alias)

		assert lines is not None and "list" in lines[0]

	for alias in ("st", "status"):
		lines = find(found, alias)

		assert lines is not None and "status" in lines[0]


def test_topics_are_found_by_name_and_by_alias():
	found = blocks()

	for name in ("statuses", "timestamps", "project selection", "list filters"):
		assert find(found, name) is not None, name

	assert find(found, "selection") == find(found, "project selection")
	assert find(found, "filters") == find(found, "list filters")
	assert find(found, "times") == find(found, "timestamps")


def test_a_command_wins_over_a_topic_alias():
	found = blocks()

	# status (command) | (statuses) (topic)
	assert find(found, "status") != find(found, "statuses")
	assert find(found, "status") is not None


def test_the_commands_topic_gathers_every_command():
	found = blocks()

	gathered = find(found, "commands")
	commands, _ = keys(found)

	assert gathered is not None
	assert len(gathered) > sum(1 for _ in commands)


def test_unknown_topics_are_not_found():
	assert find(blocks(), "there-is-no-such-thing") is None
	assert find(blocks(), "") is None


def test_a_section_is_dedented_when_shown_on_its_own():
	lines = find(blocks(), "list")

	assert lines is not None
	assert lines[0].startswith("   ")
	assert not dedent(lines)[0].startswith(" ")


def test_the_topics_named_in_the_help_command_all_exist():
	found = blocks()

	lines = find(found, "help")

	assert lines is not None

	named = "".join(lines).split("Topics:")[1]
	named = named.replace("{RESET}", "").replace("{GRAY}", "").replace(".", "")

	for entry in named.split(","):
		topic = entry.strip()

		if topic:
			assert find(found, topic) is not None, f"no help topic '{topic}'"
