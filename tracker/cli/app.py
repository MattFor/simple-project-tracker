import sys

from typing import Any

from tracker.ui.ansi import C
from tracker.ui import ansi, mentions
from tracker.core.storage import load_data
from tracker.config.settings import Settings
from tracker.ui.render import print_projects
from tracker.cli import commands, relocate, todo
from tracker.cli.entries import Context, Handler

COMMANDS: dict[str, str] = {
	"version": "version",
	"v": "version",
	"help": "help",
	"h": "help",
	"list": "list",
	"l": "list",
	"ls": "list",
	"add": "add",
	"a": "add",
	"remove": "remove",
	"rm": "remove",
	"r": "remove",
	"delete": "remove",
	"del": "remove",
	"forget": "forget",
	"f": "forget",
	"ignore": "forget",
	"completion": "completion",
	"completions": "completion",
	"check": "check",
	"c": "check",
	"cc": "check",
	"info": "check",
	"edit": "edit",
	"e": "edit",
	"note": "note",
	"n": "note",
	"sn": "note",
	"status": "status",
	"st": "status",
	"ss": "status",
	"init": "init",
	"i": "init",
	"scan": "init",
	"settings": "settings",
	"s": "settings",
	"config": "settings",
	"conf": "settings",
	"daemon": "daemon",
	"d": "daemon",
	"daemonize": "daemon",
	"daemonise": "daemon",
	"background": "daemon",
	"b": "daemon",
	"bg": "daemon",
	"path": "path",
	"p": "path",
	"where": "path",
	"stats": "stats",
	"stat": "stats",
	"summary": "stats",
	"todo": "todo",
	"todos": "todo",
	"td": "todo",
	"move": "move",
	"mv": "move",
	"relocate": "move",
	"undo": "undo",
	"u": "undo",
	"revert": "undo",
}

HANDLERS: dict[str, Handler] = {
	"version": commands.command_version,
	"help": commands.command_help,
	"list": commands.command_list,
	"add": commands.command_add,
	"remove": commands.command_remove,
	"check": commands.command_check,
	"edit": commands.command_edit,
	"init": commands.command_init,
	"settings": commands.command_settings,
	"daemon": commands.command_daemon,
	"path": commands.command_path,
	"stats": commands.command_stats,
	"undo": commands.command_undo,
	"show": commands.command_show,
	"note": commands.command_note,
	"status": commands.command_status,
	"forget": commands.command_forget,
	"completion": commands.command_completion,
	"todo": todo.command_todo,
	"move": relocate.command_move,
}

GREEDY = frozenset({"add", "completion", "edit", "move", "note", "status", "todo"})

SUBJECT = frozenset(
	{"check", "edit", "forget", "note", "path", "remove", "show", "status"}
)

ACTIONS: dict[str, frozenset[str]] = {
	"todo": frozenset(todo.ALIASES),
	"move": frozenset(relocate.NAMES),
	"edit": frozenset(commands.FIELD_ALIASES),
	"forget": frozenset({"list", "l", "show", "clear", "c", "reset", "allow"}),
	"settings": frozenset(
		{"edit", "e", "path", "p", "where", "w", "get", "g", "set", "s"}
	),
	"daemon": frozenset(
		{
			"start",
			"s",
			"stop",
			"kill",
			"k",
			"restart",
			"r",
			"status",
			"st",
			"state",
			"log",
			"logs",
			"l",
			"run",
			"foreground",
			"fg",
		}
	),
}

# Words a command keeps for itself instead of reading them as another command
KEYWORDS: dict[str, frozenset[str]] = {"list": commands.LIMIT_KEYWORDS}

LITERAL = "--"

VERBOSE_FLAGS = frozenset({"verbose", "vv"})

YES_FLAGS = frozenset({"yes", "y", "force", "f"})

COLOUR_FLAGS = frozenset({"color", "colour"})
NO_COLOUR_FLAGS = frozenset({"no-color", "no-colour", "nocolor", "nocolour"})


def normalise(token: str) -> str:
	return token.lower().strip("-")


def command_of(token: str) -> str | None:
	return COMMANDS.get(normalise(token))


def greedy(token: str) -> bool:
	name = command_of(token)

	if name is None:
		pair = fuse(token)
		name = pair[0] if pair else None

	return name in GREEDY


def fuse(token: str) -> tuple[str, str] | None:
	key = normalise(token)

	for cut in range(1, len(key)):
		name = COMMANDS.get(key[:cut])

		if name is None:
			continue

		action = key[cut:]

		if action in ACTIONS.get(name, frozenset()):
			return name, action

	return None


def expand(args: list[str]) -> list[str]:
	expanded: list[str] = []
	literal = False

	for token in args:
		if literal:
			expanded.append(token)
			continue

		if token == LITERAL:
			literal = True
			expanded.append(token)
			continue

		name = command_of(token)

		if name is not None:
			expanded.append(token)
			literal = name in GREEDY
			continue

		pair = fuse(token)

		if pair is None:
			expanded.append(token)
			continue

		literal = pair[0] in GREEDY

		expanded.extend(pair)

	return expanded


def help_request(args: list[str]) -> list[str] | None:
	for index, token in enumerate(args):
		if token == LITERAL:
			return None

		name = command_of(token)

		if name == "help":
			if index:
				for previous in reversed(args[:index]):
					owner = command_of(previous)

					if owner is not None:
						return [owner, *args[index + 1 :]]

			return args[index + 1 :]

		if name in GREEDY:
			following = index + 1

			if following == len(args) - 1 and command_of(args[following]) == "help":
				return [name]

			return None

	return None


def split(args: list[str]) -> list[tuple[str, list[str]]]:
	args = expand(args)

	wanted = help_request(args)

	if wanted is not None:
		return [("help", wanted)]

	literal = len(args)

	if LITERAL in args:
		literal = args.index(LITERAL)
		del args[literal]

	# noinspection shadowing-names
	def command_at(index: int, owner: str = "") -> str | None:
		if index >= literal:
			return None

		if normalise(args[index]) in KEYWORDS.get(owner, frozenset()):
			return None

		return command_of(args[index])

	segments: list[tuple[str, list[str]]] = []

	index = 0

	while index < len(args):
		name = command_at(index)
		subject: list[str] = []

		if name is None:
			while index < len(args) and command_at(index) is None:
				subject.append(args[index])
				index += 1

			name = command_at(index) if index < len(args) else None

			if name is None or name not in SUBJECT:
				segments.append(("show", subject))
				continue

		index += 1

		if name in GREEDY:
			segments.append((name, subject + args[index:]))
			break

		collected = list(subject)

		if index < literal and normalise(args[index]) in ACTIONS.get(name, frozenset()):
			collected.append(args[index])
			index += 1

		while index < len(args) and command_at(index, name) is None:
			collected.append(args[index])
			index += 1

		segments.append((name, collected))

	return segments


def extract_flags(args: list[str]) -> tuple[list[str], dict[str, Any]]:
	flags: dict[str, Any] = {"verbose": False, "yes": False, "colour": None}

	remaining: list[str] = []
	greedy_reached = False
	literal = False

	for token in args:
		if literal:
			remaining.append(token)
			continue

		if token == LITERAL:
			literal = True
			remaining.append(token)
			continue

		if greedy_reached and not token.startswith("-"):
			remaining.append(token)
			continue

		if greedy(token):
			greedy_reached = True

		key = normalise(token)

		if key in VERBOSE_FLAGS:
			flags["verbose"] = True
			continue

		if token.startswith("-") and key in YES_FLAGS:
			flags["yes"] = True
			continue

		if token.startswith("-") and key in NO_COLOUR_FLAGS:
			flags["colour"] = False
			continue

		if token.startswith("-") and key in COLOUR_FLAGS:
			flags["colour"] = True
			continue

		remaining.append(token)

	return remaining, flags


def main(argv: list[str] | None = None) -> int:
	args = list(sys.argv[1:] if argv is None else argv)

	args, flags = extract_flags(args)

	settings = Settings()

	colour = settings["output"]["colour"] if flags["colour"] is None else flags["colour"]
	ansi.configure(bool(colour))

	for problem in settings.problems:
		print(f"{C.YELLOW}[WARNING] {problem}{C.RESET}", file=sys.stderr)

	verbose = bool(flags["verbose"] or settings["logging"]["always_verbose"])

	context = Context(
		settings=settings,
		data=load_data(settings),
		verbose=verbose,
		assume_yes=bool(flags["yes"]),
	)

	# A note may point at a project, and these are already read
	mentions.use(context.data)

	context.log(f"settings: {settings.path}")
	context.log(f"projects: {len(context.data)}")

	if not args:
		print_projects(context.data, settings)
		return 0

	status = 0

	for name, arguments in split(args):
		handler = HANDLERS.get(name)

		if handler is None:
			print(f"[ERROR] unknown command '{name}'")
			status = 1
			continue

		try:
			status = handler(context, arguments) or status
		except KeyboardInterrupt:
			print()
			return 130
		except BrokenPipeError:
			return 0

	return status
