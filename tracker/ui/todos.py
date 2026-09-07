from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tracker.config.settings import Settings
from tracker.core.todos import (
	Todo,
	Todos,
	done_status,
	filter_todos,
	is_done,
	new_status,
	pin_numbering,
	search_todos,
	sort_todos,
	status_counts,
	status_of,
)
from tracker.ui import mentions
from tracker.ui.ansi import C, markup
from tracker.ui.render import (
	NOTE_HEADER,
	Segment,
	columns_layout,
	fields_of,
	format_fields,
	note_display,
	parse_format,
	render_table,
	short_times,
	status_colour,
	terminal_width,
	timestamp,
)
from tracker.util.text import parse_time, relative_time, wrap

SCOPE = "todos"

DEFAULT_COLUMNS = ("tid", "id", "name", "status", "created")

# A todo has no path or language, and its times are its own
FROM_PROJECT = {
	"tid": "tid",
	"id": "id",
	"name": "name",
	"status": "status",
	"last_touched": "created",
	"last_used": "updated",
}

HEADERS = {
	"tid": "TID",
	"id": "ID",
	"name": "NAME",
	"status": "STATUS",
	"created": "CREATED",
	"updated": "UPDATED",
	"done_at": "DONE",
}

FIELDS = {**HEADERS, "note": NOTE_HEADER}

SHRINKABLE = ("name", "status", "note")

LABEL_WIDTH = 14


#
# Settings
#


def view(settings: Settings) -> Settings:
	"""What a todo is drawn with: [todos.display] over [display] over the defaults."""

	return settings.scoped(SCOPE)


#
# Values
#


def note_of(todo: Todo) -> str:
	return str(todo.get("note", "") or "")


def shown_note(note: str, settings: Settings, base: str = "") -> str:
	return note_display(mentions.render(note, settings, base), base)


def note_text(todo: Todo, settings: Settings, base: str = "") -> str:
	return shown_note(note_of(todo), settings, base)


def shown_status(todo: Todo, settings: Settings) -> str:
	"""A status worth printing: the one every new todo starts with says nothing."""

	status = str(todo.get("status", ""))

	return "" if status.strip().lower() == new_status(settings) else status


def cell(todo: Todo, column: str, settings: Settings, tid: int) -> str:
	if column == "tid":
		return str(tid) if tid else "-"

	if column == "id":
		return str(todo.get("id", "-"))

	if column == "name":
		return str(todo.get("name", ""))

	if column == "status":
		return shown_status(todo, settings)

	if column in ("created", "updated", "done_at"):
		return timestamp(str(todo.get(column, "") or "-"), settings)

	if column == "note":
		return note_text(todo, settings)

	return str(todo.get(column, ""))


def colourise(value: str, column: str, todo: Todo, settings: Settings) -> str:
	# Nothing to paint, and the padding is better left plain
	if not C.enabled or not value.strip():
		return value

	if column == "name":
		# A finished todo steps back instead of shouting at you
		if is_done(todo, settings):
			return f"{C.GRAY}{value}{C.RESET}"

		return f"{C.BOLD}{value}{C.RESET}"

	if column == "status":
		return C.paint(value, status_colour(status_of(todo), settings))

	return f"{C.GRAY}{value}{C.RESET}"


#
# Table
#


def columns(settings: Settings) -> list[str]:
	"""The configured columns, as far as a todo has them.

	A todo column may be named outright, `created` as much as the `last_touched`
	it stands in for, so that [display] and [todos.display] both read sensibly.
	"""

	configured = settings["display"]["columns"]

	if not isinstance(configured, list):
		return list(DEFAULT_COLUMNS)

	wanted: list[str] = []

	for column in [str(name) for name in configured]:
		field = column if column in HEADERS else FROM_PROJECT.get(column, "")

		if field and field not in wanted:
			wanted.append(field)

	return wanted or list(DEFAULT_COLUMNS)


def layout(settings: Settings, todos: Iterable[Todo] = ()) -> list[Segment]:
	"""display.format, but only when every field in it is one a todo has."""

	template = str(settings.get("display.format", "") or "")
	named = format_fields(template)

	if named and all(field in FIELDS for field in named):
		return parse_format(template, FIELDS)

	fields = columns(settings)

	# A column of nothing but the status new todos start with is a column of nothing
	if (
		"status" in fields
		and len(fields) > 1
		and not any(shown_status(todo, settings) for todo in todos)
	):
		fields = [field for field in fields if field != "status"]

	return columns_layout(fields, settings)


def render_rows(
	items: Iterable[tuple[str, Todo]],
	settings: Settings,
	numbering: dict[str, int] | None = None,
	*,
	show_headers: bool | None = None,
	show_notes: bool | None = None,
	prefix: str = "",
	width: int | None = None,
) -> list[str]:
	items = list(items)

	if not items:
		return []

	settings = view(settings)

	numbering = numbering or {}
	todos = dict(items)

	segments = layout(settings, todos.values())
	fields = fields_of(segments)

	lines = [
		(
			key,
			[cell(todo, field, settings, numbering.get(key, 0)) for field in fields],
			note_text(todo, settings, "GRAY"),
		)
		for key, todo in items
	]

	def paint(key: str, index: int, value: str) -> str:
		return colourise(value, fields[index], todos[key], settings)

	return render_table(
		lines,
		segments,
		FIELDS,
		settings,
		paint,
		shrinkable=SHRINKABLE,
		show_headers=(
			bool(settings["display"]["show_headers"])
			if show_headers is None
			else show_headers
		),
		show_notes=(
			bool(settings["display"]["show_notes"]) if show_notes is None else show_notes
		),
		prefix=prefix,
		width=terminal_width(settings) if width is None else width,
	)


#
# Printing
#


def print_todos(
	todos: Todos,
	settings: Settings,
	options: dict[str, Any] | None = None,
) -> None:
	options = options or {}

	if not todos:
		print("no todos yet")
		return

	selected = filter_todos(dict(todos), list(options.get("filters", [])))

	search = options.get("search")

	if search:
		selected = search_todos(selected, str(search))

	if not selected:
		print("no todos found")
		return

	items = sort_todos(selected, settings)
	numbering = pin_numbering([key for key, _ in items], settings)

	for line in render_rows(items, settings, numbering):
		print(line)


def summary(todos: Todos, settings: Settings) -> str:
	counts = status_counts(todos)
	done = counts.get(done_status(settings), 0)

	colours = view(settings)

	parts = [
		C.paint(f"{count} {status}", status_colour(status, colours))
		for status, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
	]

	left = len(todos) - done
	tail = f"{len(todos)} todo{'s' if len(todos) != 1 else ''}, {left} left"

	# Every count ends on a reset, so the grey has to be picked back up
	inside = f"{C.GRAY}, ".join(parts)

	return f"{C.GRAY}{tail}  ({inside}{C.GRAY}){C.RESET}"


def _field(label: str, value: str, colour: str = "") -> None:
	if not value:
		return

	painted = C.paint(value, colour) if colour else value

	print(f"  {C.GRAY}{label.ljust(LABEL_WIDTH)}{C.RESET}{painted}")


def _stamp(value: str, settings: Settings) -> str:
	if not value:
		return ""

	moment = parse_time(value, settings["display"]["time_format"])

	if moment is None:
		return value

	relative = relative_time(moment, short=short_times(settings))

	return f"{value}  {C.GRAY}({relative}){C.RESET}"


def print_todo(todo: Todo, settings: Settings, tid: int = 0) -> None:
	settings = view(settings)

	name = str(todo.get("name", ""))
	status = status_of(todo)

	print(f"{C.BOLD}{name}{C.RESET} {C.GRAY}#{todo.get('id', '-')}{C.RESET}")
	print(f"{C.GRAY}{'-' * min(70, max(20, len(name) + 20))}{C.RESET}")

	_field("ID", str(todo.get("id", "-")))
	_field("TID", str(tid) if tid else "-")
	_field("Status", status, status_colour(status, settings))
	_field("Created", _stamp(str(todo.get("created", "")), settings))
	_field("Updated", _stamp(str(todo.get("updated", "")), settings))
	_field("Done at", _stamp(str(todo.get("done_at", "")), settings))

	about = mentions.projects_of(todo, settings)

	if about:
		print(f"\n{C.BOLD}Projects{C.RESET}")

		for path, project in about:
			_field(
				f"#{project.get('id', '-')}",
				Path(path).name,
				status_colour(status_of(project), settings),
			)

	note = note_of(todo)

	if note:
		print(f"\n{C.BOLD}Note{C.RESET}")

		for line in note.splitlines() or [note]:
			shown = markup(mentions.render(line, settings, "GRAY"), "GRAY")

			for piece in wrap(shown, 70) or [""]:
				print(f"  {C.GRAY}{piece}{C.RESET}")
