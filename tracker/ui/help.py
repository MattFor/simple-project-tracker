import re

from tracker.config import paths
from tracker.config.metadata import Metadata
from tracker.ui.ansi import C

# "   {YELLOW}list{RESET}, {GRAY}l, ls, --list{RESET}"
_COMMAND = re.compile(r"^ {3}\{YELLOW\}(\w+)\{RESET\}")

# "{BOLD}List filters:{RESET}"
_TOPIC = re.compile(r"^\{BOLD\}([^{}]+?):?\{RESET\}\s*$")

COLOURS = (
	"BOLD",
	"DIM",
	"RED",
	"CYAN",
	"GRAY",
	"BLUE",
	"GREEN",
	"WHITE",
	"YELLOW",
	"MAGENTA",
	"RESET",
)

TOPIC_ALIASES = {
	"selection": "project selection",
	"selectors": "project selection",
	"select": "project selection",
	"ids": "project selection",
	"filter": "list filters",
	"filters": "list filters",
	"format": "row format",
	"formats": "row format",
	"row": "row format",
	"columns": "row format",
	"note": "notes",
	"option": "options",
	"flag": "options",
	"flags": "options",
	"short": "short forms",
	"fuse": "short forms",
	"fusing": "short forms",
	"config": "configuration",
	"conf": "configuration",
	"example": "examples",
	"time": "timestamps",
	"times": "timestamps",
	"timestamp": "timestamps",
	"status": "statuses",
	"state": "statuses",
	"states": "statuses",
	"roots": "sync",
	"root": "sync",
	"shared": "sync",
	"sharing": "sync",
	"machines": "sync",
	"portable": "sync",
	"syncthing": "sync",
}

Block = tuple[str, str, list[str]]


#
# Reading
#


def _source() -> str | None:
	try:
		return paths.help_file().read_text(encoding="utf-8")
	except OSError as error:
		print(f"[ERROR] could not read the help file: {error}")
		print(f"it should live at {paths.help_file()}")

		return None


def _render(text: str, project: Metadata) -> str:
	replacements = {
		"PROJECT_NAME": project.name.capitalize(),
		"PROJECT_VERSION": project.version,
		"PROJECT_AUTHOR": project.author,
		**{name: getattr(C, name) for name in COLOURS},
	}

	for key, value in replacements.items():
		text = text.replace(f"{{{key}}}", str(value))

	return text


#
# Sections
#


def dedent(lines: list[str]) -> list[str]:
	indents = [len(line) - len(line.lstrip()) for line in lines if line.strip()]

	margin = min(indents, default=0)

	return [line[margin:] if line.strip() else "" for line in lines]


def _trim(lines: list[str]) -> list[str]:
	while lines and not lines[0].strip():
		_ = lines.pop(0)

	while lines and not lines[-1].strip():
		_ = lines.pop()

	return lines


def parse(text: str) -> list[Block]:
	blocks: list[Block] = []

	kind, title, lines = "preamble", "", []

	for line in text.splitlines():
		command = _COMMAND.match(line)
		topic = None if command else _TOPIC.match(line)

		if command is None and topic is None:
			lines.append(line)
			continue

		blocks.append((kind, title, _trim(lines)))

		if command is not None:
			kind, title = "command", command.group(1)
		else:
			assert topic is not None
			kind, title = "topic", topic.group(1).strip()

		lines = [line]

	blocks.append((kind, title, _trim(lines)))

	return [block for block in blocks if block[2]]


def _every_command(blocks: list[Block]) -> list[str]:
	lines: list[str] = []

	for kind, _, block in blocks:
		if kind != "command":
			continue

		if lines:
			lines.append("")

		lines.extend(block)

	return lines


def find(blocks: list[Block], name: str) -> list[str] | None:
	from tracker.cli.app import COMMANDS

	key = name.strip().lower().strip("-")

	if not key:
		return None

	command = COMMANDS.get(key)

	if command is not None:
		for kind, title, lines in blocks:
			if kind == "command" and title == command:
				return lines

	wanted = TOPIC_ALIASES.get(key, key)

	if wanted == "commands":
		return _every_command(blocks) or None

	for kind, title, lines in blocks:
		if kind == "topic" and title.lower() == wanted:
			return lines

	return None


def keys(blocks: list[Block]) -> tuple[list[str], list[str]]:
	commands = [title for kind, title, _ in blocks if kind == "command"]
	topics = [title.lower() for kind, title, _ in blocks if kind == "topic"]

	return commands, topics


#
# Printing
#


def print_help(project: Metadata) -> None:
	text = _source()

	if text is None:
		return

	print(_render(text, project))


def print_topic(project: Metadata, name: str) -> int:
	from difflib import get_close_matches

	text = _source()

	if text is None:
		return 1

	blocks = parse(text)
	lines = find(blocks, name)

	if lines is not None:
		print(_render("\n".join(dedent(lines)), project))
		return 0

	commands, topics = keys(blocks)

	print(f"[ERROR] no help for '{name}'")

	candidates = commands + topics + sorted(TOPIC_ALIASES)
	close = get_close_matches(name.strip().lower(), candidates, n=1, cutoff=0.6)

	if close:
		print(f"{C.GRAY}        maybe '{close[0]}'?{C.RESET}")

	print(f"\n{C.BOLD}Commands{C.RESET}")
	print(f"  {', '.join(commands)}")

	print(f"\n{C.BOLD}Topics{C.RESET}")
	print(f"  {', '.join(topics)}")

	return 1
