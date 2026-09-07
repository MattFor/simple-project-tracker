import time
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from tracker.config import paths
from tracker.config.settings import Settings
from tracker.config.settings import settings as default_settings
from tracker.core import entries as shared
from tracker.core.entries import (
	ALL_SELECTORS,
	Rows,
	Space,
	filter_entries,
	search_entries,
	status_counts,
	status_filter,
	status_matches,
	status_of,
	status_values,
)
from tracker.core.storage import read, write
from tracker.util.text import parse_time

__all__ = [
	"ALL_SELECTORS",
	"EDIT_FIELDS",
	"FIELD_ALIASES",
	"TODOS",
	"Todo",
	"Todos",
	"done_status",
	"filter_todos",
	"is_done",
	"key_of",
	"load_todos",
	"new_status",
	"new_todo",
	"next_id",
	"normalise",
	"pin_numbering",
	"pin_todos",
	"resolve_selection",
	"restore",
	"save_todos",
	"search_todos",
	"select_todos",
	"set_field",
	"sort_todos",
	"stamp",
	"status_counts",
	"status_filter",
	"status_matches",
	"status_of",
	"status_values",
	"temporary_ids",
	"todo_path",
]


class Todo(TypedDict):
	id: int

	name: str
	status: str

	note: NotRequired[str]

	created: NotRequired[str]
	updated: NotRequired[str]
	done_at: NotRequired[str]


Todos = dict[str, Todo]

EDIT_FIELDS = ("name", "status", "note")

FIELD_ALIASES = {
	"name": "name",
	"title": "name",
	"nm": "name",
	"status": "status",
	"stat": "status",
	"st": "status",
	"s": "status",
	"note": "note",
	"notes": "note",
	"nt": "note",
	"n": "note",
}


#
# Values
#


def new_status(settings: Settings) -> str:
	return str(settings["todos"]["new_status"] or "todo").strip().lower()


def done_status(settings: Settings) -> str:
	return str(settings["todos"]["done_status"] or "done").strip().lower()


def is_done(todo: Todo, settings: Settings) -> bool:
	return status_of(todo) == done_status(settings)


def stamp(settings: Settings) -> str:
	return time.strftime(settings["display"]["time_format"])


#
# The entries
#


def key_of(todo: Todo) -> str:
	return str(todo["id"])


def next_id(todos: Todos) -> int:
	known = [todo["id"] for todo in todos.values() if "id" in todo]

	return max(known, default=0) + 1


def new_todo(
	name: str,
	*,
	status: str,
	note: str = "",
	todo_id: int = 0,
	created: str = "",
) -> Todo:
	todo: Todo = {
		"id": todo_id,
		"name": name,
		"status": status,
		"note": note,
	}

	if created:
		todo["created"] = created
		todo["updated"] = created

	return todo


def set_field(todo: Todo, field: str, value: str) -> None:
	if field == "name":
		todo["name"] = value
	elif field == "status":
		todo["status"] = value
	elif field == "note":
		todo["note"] = value


def normalise(todos: Any) -> Todos:
	if not isinstance(todos, dict):
		return {}

	entries: dict[Any, Any] = todos

	cleaned: Todos = {}
	used_ids: set[int] = set()

	for key, todo in entries.items():
		if not isinstance(todo, dict):
			continue

		entry: dict[str, Any] = todo

		todo_id = entry.get("id")

		if not isinstance(todo_id, int) or todo_id in used_ids:
			try:
				todo_id = int(str(key))
			except ValueError:
				todo_id = 0

		if todo_id < 1 or todo_id in used_ids:
			todo_id = max(used_ids, default=0) + 1

		used_ids.add(todo_id)

		entry["id"] = todo_id
		entry["name"] = str(entry.get("name") or "").strip() or f"todo {todo_id}"
		entry["status"] = str(entry.get("status") or "unknown")
		entry["note"] = str(entry.get("note") or "")

		cleaned[str(todo_id)] = entry  # pyright: ignore[reportArgumentType]

	return cleaned


#
# Storage
#


def todo_path(settings: Settings | None = None) -> Path:
	settings = settings or default_settings

	return paths.todo_file(settings.get("todos.database"))


def load_todos(settings: Settings | None = None) -> Todos:
	return read(todo_path(settings), normalise, "todo list")


def save_todos(
	todos: Todos, settings: Settings | None = None, *, undoable: bool = True
) -> bool:
	return write(todo_path(settings), todos, "todo list", undoable=undoable)


def restore(settings: Settings | None = None) -> tuple[Todos, Todos] | None:
	from tracker.core.undo import swap

	settings = settings or default_settings

	return swap(
		todo_path(settings),
		load_todos(settings),
		normalise,
		lambda todos: save_todos(todos, settings, undoable=False),
	)


#
# Sorting
#


def sort_todos(todos: Todos, settings: Settings) -> list[tuple[str, Todo]]:
	sort_by = str(settings["todos"]["sort"])
	time_format: str = settings["display"]["time_format"]

	def key(item: tuple[str, Todo]) -> tuple[Any, int]:
		_, todo = item

		identifier = int(todo.get("id", 0))

		if sort_by == "name":
			return todo.get("name", "").lower(), identifier

		if sort_by == "status":
			return status_of(todo), identifier

		if sort_by in ("created", "updated"):
			moment = parse_time(str(todo.get(sort_by, "")), time_format)

			return (moment.timestamp() if moment else float("-inf")), identifier

		return identifier, identifier

	return sorted(todos.items(), key=key, reverse=bool(settings["todos"]["newest_first"]))


#
# The space
#


def _view(settings: Settings) -> tuple[Path, str]:
	return paths.todo_view_file(), str(todo_path(settings))


def _texts(key: str, todo: Todo) -> list[str]:
	del key

	return [str(todo.get("name", ""))]


def _notes(key: str, todo: Todo) -> list[str]:
	del key

	return [str(todo.get("note", "") or "")]


def _rows(rows: Rows, settings: Settings, numbering: dict[str, int]) -> list[str]:
	from tracker.ui.todos import render_rows
	from tracker.ui.todos import view as todo_view

	# Already the td view, so the forced columns are not read back over
	shown = todo_view(settings)

	try:
		shown = shown.override("display.format", "").override(
			"display.columns", ["id", "tid", "name", "status", "created"]
		)
	except (KeyError, ValueError):
		shown = todo_view(settings)

	return render_rows(
		rows, shown, numbering, show_headers=True, show_notes=False, prefix="  "
	)


TODOS = Space(
	noun="todo",
	view=_view,
	sort=sort_todos,
	texts=_texts,
	extra=_notes,
	rows=_rows,
)


#
# Numbering
#


def pin_numbering(keys: list[str], settings: Settings) -> dict[str, int]:
	return shared.pin_numbering(keys, settings, TODOS)


def pin_todos(todos: Todos, settings: Settings) -> dict[str, int]:
	return shared.pin_entries(todos, settings, TODOS)


def temporary_ids(todos: Todos, settings: Settings) -> dict[str, int]:
	return shared.temporary_ids(todos, settings, TODOS)


#
# Filtering and selecting
#


def filter_todos(todos: Todos, filters: list[str], *, quiet: bool = False) -> Todos:
	return filter_entries(todos, filters, TODOS, quiet=quiet)


def search_todos(todos: Todos, search: str) -> Todos:
	return search_entries(todos, search, TODOS)


def resolve_selection(
	todos: Todos,
	settings: Settings,
	selectors: list[str],
	*,
	quiet: bool = False,
) -> tuple[Todos, list[str]]:
	return shared.resolve_selection(todos, settings, selectors, TODOS, quiet=quiet)


def select_todos(
	todos: Todos,
	settings: Settings,
	selectors: list[str],
	*,
	quiet: bool = False,
) -> Todos:
	return shared.select_entries(todos, settings, selectors, TODOS, quiet=quiet)
