import os
import re
import sys
import shutil

from typing import Any
from pathlib import Path
from collections.abc import Callable, Iterable

from tracker.ui.ansi import C
from tracker.config.settings import Settings
from tracker.core.inspect import detect_manifest
from tracker.core.models import Project, Projects

from tracker.util.text import (
	flatten,
	pad,
	parse_time,
	relative_time,
	truncate,
	wrap,
)

HEADERS = {
	"tid": "TID",
	"id": "ID",
	"name": "NAME",
	"path": "PATH",
	"status": "STATUS",
	"last_touched": "LAST TOUCHED",
	"version": "VERSION",
	"language": "LANG",
}

NOTE_HEADER = "NOTE"

FIELD_HEADERS = {**HEADERS, "note": NOTE_HEADER}

SHRINKABLE = ("path", "name", "status", "version", "language", "note")

_PLACEHOLDER = re.compile(r"\$(?:\{([<>])?(\w+)\}|([<>])?(\w+))")

Segment = tuple[str, str, str]

MINIMUM_COLUMN = 8
MINIMUM_NOTE = 6


#
# Terminal
#


def terminal_width(settings: Settings) -> int:
	configured = settings.get("display.max_width", 0)

	if isinstance(configured, int) and configured > 0:
		return configured

	if not sys.stdout.isatty() and not os.environ.get("COLUMNS"):
		return 0

	return shutil.get_terminal_size(fallback=(80, 24)).columns


#
# Values
#


def visible_columns(settings: Settings) -> list[str]:
	columns = settings["display"]["columns"]

	if not isinstance(columns, list):
		return ["name", "status", "last_touched"]

	chosen: list[str] = [str(column) for column in columns]

	return [column for column in chosen if column in HEADERS]


def parse_format(template: str) -> list[Segment]:
	segments: list[Segment] = []
	index = 0

	for match in _PLACEHOLDER.finditer(template):
		if match.start() > index:
			segments.append(("literal", template[index : match.start()], ""))

		align = match.group(1) or match.group(3) or "<"
		name = match.group(2) or match.group(4)

		if name in FIELD_HEADERS:
			segments.append(("field", name, align))
		else:
			segments.append(("literal", match.group(0), ""))

		index = match.end()

	if index < len(template):
		segments.append(("literal", template[index:], ""))

	return segments


def column_separator(settings: Settings) -> str:
	separator: str = settings["display"]["vertical_separator"] or " "

	if settings["output"]["compact"]:
		return separator.strip() or " "

	return separator


def layout(settings: Settings) -> tuple[list[Segment], bool]:
	template = str(settings.get("display.format", "") or "")

	if template.strip():
		segments = parse_format(template)

		if any(kind == "field" for kind, _, _ in segments):
			return segments, True

	columns = visible_columns(settings)

	if not columns:
		return [], False

	separator = column_separator(settings)
	built: list[Segment] = []

	for index, column in enumerate(columns):
		if index:
			built.append(("literal", separator, ""))

		built.append(("field", column, "<"))

	return built, False


def status_colour(status: str, settings: Settings) -> str:
	colours = settings.get("display.status_colours", {})

	if not isinstance(colours, dict):
		return ""

	table: dict[str, Any] = colours

	return str(table.get(status.lower(), ""))


def timestamp(value: str, settings: Settings) -> str:
	if not settings["display"]["relative_times"]:
		return value

	moment = parse_time(value, settings["display"]["time_format"])

	return relative_time(moment) if moment else value


def cell(path: str, project: Project, column: str, settings: Settings, tid: int) -> str:
	if column == "tid":
		return str(tid) if tid else "-"

	if column == "id":
		return str(project.get("id", "-"))

	if column == "name":
		return Path(path).name

	if column == "path":
		if settings["output"]["absolute_paths"]:
			return path

		try:
			return os.path.relpath(path)
		except ValueError:
			return path

	if column == "last_touched":
		return timestamp(str(project.get("last_touched", "unknown")), settings)

	if column == "note":
		return flatten(note_of(project))

	if column in ("version", "language"):
		manifest = detect_manifest(path)

		if manifest is None:
			return "-"

		return (manifest.version or "-") if column == "version" else manifest.language

	return str(project.get(column, ""))


def colourise(value: str, column: str, project: Project, settings: Settings) -> str:
	if column == "name":
		return f"{C.BOLD}{value}{C.RESET}" if C.enabled else value

	if column == "status":
		return C.paint(value, status_colour(str(project.get("status", "")), settings))

	if column in ("path", "last_touched", "id", "tid"):
		return f"{C.GRAY}{value}{C.RESET}" if C.enabled else value

	return value


def note_of(project: Project) -> str:
	return str(project.get("note", "") or "")


#
# Table
#


def render_rows(
	items: Iterable[tuple[str, Project]],
	settings: Settings,
	temporary_ids: dict[str, int] | None = None,
	*,
	show_headers: bool | None = None,
	show_notes: bool | None = None,
	prefix: str = "",
	width: int | None = None,
) -> list[str]:
	items = list(items)

	if not items:
		return []

	temporary_ids = temporary_ids or {}

	segments, templated = layout(settings)

	fields = [name for kind, name, _ in segments if kind == "field"]
	aligns = [align for kind, _, align in segments if kind == "field"]

	if not fields:
		return ["no valid columns configured"]

	if show_headers is None:
		show_headers = bool(settings["display"]["show_headers"])

	if show_notes is None:
		show_notes = bool(settings["display"]["show_notes"])

	if width is None:
		width = terminal_width(settings)

	separator = column_separator(settings)
	horizontal: str = settings["display"]["horizontal_separator"]

	note_position: str = settings["display"]["note_position"]
	note_minimum: int = max(MINIMUM_NOTE, int(settings.get("display.note_min_width", 24)))

	rows = [
		(
			path,
			project,
			[cell(path, project, field, settings, temporary_ids.get(path, 0)) for field in fields],
		)
		for path, project in items
	]

	label_width = show_headers or not templated

	widths = [
		max(
			len(FIELD_HEADERS[field]) if label_width else 0,
			*(len(row[2][index]) for row in rows),
		)
		for index, field in enumerate(fields)
	]

	literals = sum(len(text) for kind, text, _ in segments if kind == "literal")

	available = width - len(prefix) if width else 0

	_shrink(fields, widths, literals, available)

	for _, _, values in rows:
		for index, value in enumerate(values):
			values[index] = truncate(value, widths[index])

	# noinspection shadowing-names
	def compose(values: list[str], render: Callable[[str, int], str]) -> str:
		pieces: list[str] = []
		position = 0

		for kind, text, _ in segments:
			if kind == "literal":
				pieces.append(text)
				continue

			pieces.append(render(values[position], position))
			position += 1

		return "".join(pieces)

	table_width = sum(widths) + literals

	note_space = available - table_width - len(separator) if available else 0

	if not available:
		note_space = 10**6

	trailing_notes = show_notes and "note" not in fields

	notes: dict[str, tuple[str, bool]] = {}

	for path, project, _ in rows:
		note = flatten(note_of(project))

		if not trailing_notes or not note:
			continue

		if note_position == "below":
			notes[path] = (note, False)
			continue

		if note_position == "inline":
			inline = note_space >= MINIMUM_NOTE
		else:
			inline = note_space >= note_minimum and len(note) <= note_space

		notes[path] = (note, inline)

	inline_width = max(
		(min(len(note), note_space) for note, inline in notes.values() if inline),
		default=0,
	)

	lines: list[str] = []

	if show_headers:
		labels = [FIELD_HEADERS[field] for field in fields]
		header = compose(
			labels,
			lambda value, index: pad(value, widths[index], aligns[index] == ">"),
		)

		if inline_width:
			header = f"{header}{separator}{pad(NOTE_HEADER, inline_width)}"

		lines.append(prefix + f"{C.BOLD}{header.rstrip()}{C.RESET}")

		if horizontal.strip():
			bars = [horizontal * width_ for width_ in widths]
			rule = compose(bars, lambda value, _: value)

			if inline_width:
				rule = f"{rule}{separator}{horizontal * inline_width}"

			lines.append(prefix + f"{C.GRAY}{rule.rstrip()}{C.RESET}")

	for path, project, values in rows:

		# noinspection shadowing-names,default-argument
		def paint(value: str, index: int, project: Project = project) -> str:
			shown = pad(value, widths[index], aligns[index] == ">")

			return colourise(shown, fields[index], project, settings)

		line = compose(values, paint)

		note, inline = notes.get(path, ("", False))

		if note and inline:
			shown = truncate(note, note_space)
			line = f"{line}{separator}{C.GRAY}{shown}{C.RESET}"

		lines.append(prefix + line.rstrip())

		if note and not inline:
			indent = prefix + "    "
			wrap_width = (available - 4) if available else 0

			for piece in wrap(note, wrap_width) if wrap_width else [note]:
				lines.append(f"{indent}{C.GRAY}{piece}{C.RESET}")

	return lines


def _shrink(fields: list[str], widths: list[int], literals: int, available: int) -> None:
	if not available:
		return

	while True:
		overflow = sum(widths) + literals - available

		if overflow <= 0:
			return

		candidates = [
			index
			for index, field in enumerate(fields)
			if field in SHRINKABLE and widths[index] > MINIMUM_COLUMN
		]

		if not candidates:
			return

		widest = max(candidates, key=lambda index: widths[index])

		room = widths[widest] - MINIMUM_COLUMN
		widths[widest] -= min(room, overflow)


def print_projects(
	projects: Projects,
	settings: Settings,
	options: dict[str, Any] | None = None,
) -> None:
	from tracker.core.selection import (
		filter_projects,
		regex_projects,
		search_projects,
		sort_projects,
	)

	options = options or {}

	if not projects:
		print("no projects found")
		return

	ordered = sort_projects(projects, settings)
	temporary_ids = {path: tid for tid, (path, _) in enumerate(ordered, 1)}

	selected = dict(ordered)

	selected = filter_projects(selected, settings["display"]["filter"])

	for expression in options.get("filters", []):
		selected = filter_projects(selected, [expression])

	search = options.get("search")

	if search:
		selected = search_projects(selected, search)

	expression = options.get("regex")

	if expression:
		matched = regex_projects(selected, expression)

		if matched is None:
			return

		selected = matched

	if not selected:
		print("no projects found")
		return

	limit = options.get("limit")

	if limit is None:
		limit = settings["display"]["list_limit"]

	try:
		limit = int(limit)
	except (TypeError, ValueError):
		limit = 0

	items = list(selected.items())

	if 0 < limit < len(items):
		items = items[:limit]

	for line in render_rows(items, settings, temporary_ids):
		print(line)


def format_project(
	path: str,
	project: Project,
	settings: Settings,
	temporary_ids: dict[str, int] | None = None,
	among: Projects | None = None,
	prefix: str = "",
) -> str:
	items = list(among.items()) if among else [(path, project)]

	lines = render_rows(
		items,
		settings,
		temporary_ids,
		show_headers=False,
		show_notes=False,
		prefix=prefix,
	)

	if among:
		index = [item[0] for item in items].index(path)
		return lines[index]

	return lines[0] if lines else prefix + path
