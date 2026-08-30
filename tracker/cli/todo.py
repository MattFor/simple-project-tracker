from typing import Any, final

from tracker.ui.ansi import C
from tracker.ui import mentions
from tracker.ui.help import print_topic
from tracker.core.entries import parse_filter
from tracker.config.metadata import project as metadata

from tracker.cli.entries import (
	Context,
	Entries,
	Kind,
	confirm,
	plural,
	report_undo,
)

from tracker.core.todos import (
	ALL_SELECTORS,
	FIELD_ALIASES,
	TODOS,
	Todos,
	done_status,
	key_of,
	load_todos,
	new_status,
	new_todo,
	next_id,
	save_todos,
	set_field,
	sort_todos,
	stamp,
	status_matches,
	status_of,
	status_values,
)

from tracker.ui.todos import (
	note_text,
	print_todo,
	print_todos,
	render_rows,
	shown_note,
	summary,
)

ALIASES = {
	"list": "list",
	"l": "list",
	"ls": "list",
	"add": "add",
	"a": "add",
	"new": "add",
	"remove": "remove",
	"rm": "remove",
	"r": "remove",
	"del": "remove",
	"delete": "remove",
	"drop": "remove",
	"edit": "edit",
	"e": "edit",
	"note": "note",
	"n": "note",
	"nt": "note",
	"status": "status",
	"st": "status",
	"s": "status",
	"rename": "rename",
	"name": "rename",
	"mv": "rename",
	"done": "done",
	"d": "done",
	"x": "done",
	"finish": "done",
	"complete": "done",
	"reopen": "reopen",
	"ro": "reopen",
	"undone": "reopen",
	"open": "reopen",
	"o": "reopen",
	"check": "check",
	"c": "check",
	"info": "check",
	"show": "check",
	"clear": "clear",
	"cl": "clear",
	"purge": "clear",
	"undo": "undo",
	"u": "undo",
	"revert": "undo",
	"stats": "stats",
	"summary": "stats",
	"help": "help",
	"h": "help",
}

TAKES_SELECTION = frozenset(
	{"check", "done", "edit", "note", "remove", "rename", "reopen", "status"}
)


def action_of(token: str) -> str:
	return ALIASES.get(token.lower().strip("-"), "")


@final
class TodoKind(Kind):
	space = TODOS

	fields = FIELD_ALIASES
	greedy = ("name", "note")
	required = ("name",)

	empty = "no todos yet"
	hint = "t td list shows what there is"

	hints = (
		("t td list s:<status>", "only those todos"),
		("t td <todo> st <status>", "set one"),
		("t td done <todo>", "mark it finished"),
	)

	def load(self, context: Context) -> Todos:
		kept = context.options.get("todos")

		if kept is None:
			kept = load_todos(context.settings)

			context.options["todos"] = kept

			# A note may point at a project, and a project check looks here
			mentions.use_todos(kept)

		todos: Todos = kept

		return todos

	def save(self, context: Context, entries: Entries) -> bool:
		return save_todos(entries, context.settings)

	def rows(
		self,
		context: Context,
		entries: Entries,
		numbering: dict[str, int],
		*,
		prefix: str = "",
		headers: bool = False,
		notes: bool | None = None,
	) -> list[str]:
		return render_rows(
			sort_todos(entries, context.settings),
			context.settings,
			numbering,
			show_headers=headers,
			show_notes=notes,
			prefix=prefix,
		)

	def details(self, context: Context, key: str, entry: Any, tid: int) -> None:
		del key

		print_todo(entry, context.settings, tid)

	def set(self, context: Context, entry: Any, name: str, value: str) -> None:
		set_field(entry, name, value)

		moment = stamp(context.settings)
		entry["updated"] = moment

		if name != "status":
			return

		if value.strip().lower() == done_status(context.settings):
			entry["done_at"] = moment
		else:
			_ = entry.pop("done_at", None)

	def listing(self, context: Context, args: list[str]) -> int:
		return action_list(context, args)

	def note(self, text: str, context: Context, base: str = "") -> str:
		return shown_note(text, context.settings, base)


TODO = TodoKind()


#
# The actions of its own
#


def action_list(context: Context, args: list[str]) -> int:
	options: dict[str, Any] = {"filters": []}

	for token in args:
		if token.lower() in ALL_SELECTORS:
			continue

		filtered = parse_filter(token)

		if filtered is not None:
			options["filters"].append(filtered)
			continue

		options["search"] = token

	print_todos(TODO.load(context), context.settings, options)

	return 0


def action_add(context: Context, args: list[str]) -> int:
	name = " ".join(args).strip()

	if not name:
		print("[ERROR] add requires something to do")
		print(f"{C.GRAY}        t td add read the manual{C.RESET}")

		return 1

	settings = context.settings
	todos = TODO.load(context)

	todo = new_todo(
		name,
		status=new_status(settings),
		todo_id=next_id(todos),
		created=stamp(settings),
	)

	key = key_of(todo)
	todos[key] = todo

	if not TODO.save(context, todos):
		return 1

	# The whole list is renumbered so every row keeps a usable TID
	numbering = TODO.pin(context, todos)

	print(f"added {TODO.one_row(context, {key: todo}, numbering)}")

	return 0


def action_clear(context: Context, args: list[str]) -> int:
	settings = context.settings
	todos = TODO.load(context)

	wanted = status_values(" ".join(args)) or [done_status(settings)]

	matched = {key: todo for key, todo in todos.items() if status_matches(todo, wanted)}

	if not matched:
		print(f"no todos are {', '.join(wanted)}")
		return 0

	question = f"remove {plural(len(matched), 'todo')} marked {', '.join(wanted)}?"

	if not confirm(context, question):
		print("cancelled")
		return 1

	for key in matched:
		del todos[key]

	if not TODO.save(context, todos):
		return 1

	print(f"cleared {plural(len(matched), 'todo')}")

	return 0


def action_mark(context: Context, args: list[str], status: str) -> int:
	if not args:
		return TODO.missing(
			"done" if status == done_status(context.settings) else "reopen"
		)

	todos = TODO.load(context)
	selected = TODO.chosen(context, todos, args, "status")

	if selected is None:
		return 1

	return TODO.write(context, todos, selected, [("status", status)])


def action_stats(context: Context) -> int:
	todos = TODO.load(context)

	if not todos:
		print(TODO.empty)
		return 0

	print(summary(todos, context.settings))

	finished = done_status(context.settings)

	oldest = min(
		(todo for todo in todos.values() if status_of(todo) != finished),
		key=lambda todo: int(todo.get("id", 0)),
		default=None,
	)

	if oldest is not None:
		note = note_text(oldest, context.settings, "GRAY")
		tail = f"  {note}" if note else ""

		print(f"{C.GRAY}oldest open: {oldest['name']}{tail}{C.RESET}")

	return 0


def action_undo(context: Context) -> int:
	from tracker.core.todos import restore

	swapped = restore(context.settings)

	if swapped is None:
		print("nothing to undo")
		return 1

	report_undo(*swapped, "todo", "t td undo again")

	return 0


#
# The command
#


def command_todo(context: Context, args: list[str]) -> int:
	if args and action_of(args[-1]) == "help":
		return print_topic(metadata, "todo")

	action = action_of(args[0]) if args else "list"
	arguments = args[1:]

	# A td may come before its action
	if not action and len(args) > 1:
		following = action_of(args[1])

		if following in TAKES_SELECTION:
			action, arguments = following, [args[0], *args[2:]]

	context.log(f"todos: {len(TODO.load(context))}")

	if not action:
		return TODO.show(context, args)

	match action:
		case "help":
			return print_topic(metadata, "todo")

		case "list":
			return action_list(context, arguments)

		case "add":
			return action_add(context, arguments)

		case "remove":
			return TODO.remove(context, arguments)

		case "clear":
			return action_clear(context, arguments)

		case "edit":
			return TODO.edit(context, arguments)

		case "note":
			return TODO.field(context, arguments, "note")

		case "rename":
			return TODO.field(context, arguments, "name")

		case "status":
			if not arguments:
				return TODO.statuses(context)

			return TODO.field(context, arguments, "status")

		case "done":
			return action_mark(
				context,
				arguments,
				done_status(context.settings),
			)

		case "reopen":
			return action_mark(
				context,
				arguments,
				new_status(context.settings),
			)

		case "check":
			return TODO.check(context, arguments)

		case "stats":
			return action_stats(context)

		case _:
			return action_undo(context)
