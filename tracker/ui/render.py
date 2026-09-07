import os
import re
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from tracker.config.settings import Settings
from tracker.core.inspect import detect_manifest
from tracker.core.models import Project, Projects
from tracker.ui.ansi import C, markup
from tracker.util.text import (
	abbreviate,
	flatten,
	pad,
	parse_time,
	relative_time,
	shorten,
	truncate,
	visible_length,
	wrap,
)

HEADERS = {
	"tid": "TID",
	"id": "ID",
	"name": "NAME",
	"path": "PATH",
	"status": "STATUS",
	"last_touched": "LAST TOUCHED",
	"last_used": "LAST USED",
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


def format_fields(template: str) -> list[str]:
	"""Every $field a format string names, whether or not it is one that exists."""

	return [match.group(2) or match.group(4) for match in _PLACEHOLDER.finditer(template)]


def parse_format(
	template: str, fields: Mapping[str, str] = FIELD_HEADERS
) -> list[Segment]:
	segments: list[Segment] = []
	index = 0

	for match in _PLACEHOLDER.finditer(template):
		if match.start() > index:
			segments.append(("literal", template[index : match.start()], ""))

		align = match.group(1) or match.group(3) or "<"
		name = match.group(2) or match.group(4)

		if name in fields:
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


def columns_layout(columns: Iterable[str], settings: Settings) -> list[Segment]:
	separator = column_separator(settings)
	built: list[Segment] = []

	for index, column in enumerate(columns):
		if index:
			built.append(("literal", separator, ""))

		built.append(("field", column, "<"))

	return built


def fields_of(segments: list[Segment]) -> list[str]:
	return [name for kind, name, _ in segments if kind == "field"]


def layout(settings: Settings) -> list[Segment]:
	template = str(settings.get("display.format", "") or "")

	if template.strip():
		segments = parse_format(template)

		if any(kind == "field" for kind, _, _ in segments):
			return segments

	columns = visible_columns(settings)

	if not columns:
		return []

	return columns_layout(columns, settings)


def project_name(path: str, settings: Settings) -> str:
	name = Path(path).name

	width = settings.get("display.name_max_width", 0)
	style = str(settings.get("display.name_style", "truncate")).lower()

	if not isinstance(width, int) or width <= 0 or style == "full":
		return name

	if len(name) <= width:
		return name

	if style == "abbreviate":
		return abbreviate(name, width)

	return shorten(name, width, str(settings.get("display.name_continuator", "...")))


def status_colour(status: str, settings: Settings) -> str:
	colours = settings.get("display.status_colours", {})

	if not isinstance(colours, dict):
		return ""

	table: dict[str, Any] = colours

	return str(table.get(status.lower(), ""))


def short_times(settings: Settings) -> bool:
	return str(settings.get("display.relative_style", "long")).lower() == "short"


def timestamp(value: str, settings: Settings) -> str:
	if not settings["display"]["relative_times"]:
		return value

	moment = parse_time(value, settings["display"]["time_format"])

	if moment is None:
		return value

	return relative_time(moment, short=short_times(settings))


def cell(path: str, project: Project, column: str, settings: Settings, tid: int) -> str:
	if column == "tid":
		return str(tid) if tid else "-"

	if column == "id":
		return str(project.get("id", "-"))

	if column == "name":
		return project_name(path, settings)

	if column == "path":
		if settings["output"]["absolute_paths"]:
			return path

		try:
			return os.path.relpath(path)
		except ValueError:
			return path

	if column == "last_touched":
		return timestamp(str(project.get("last_touched", "unknown")), settings)

	if column == "last_used":
		return timestamp(str(project.get("last_used", "") or "never"), settings)

	if column == "note":
		return note_text(project)

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

	if column in ("path", "last_touched", "last_used", "id", "tid"):
		return f"{C.GRAY}{value}{C.RESET}" if C.enabled else value

	return value


def note_of(project: Project) -> str:
	return str(project.get("note", "") or "")


def note_display(note: str, base: str = "") -> str:
	shown = markup(flatten(note), base)

	# Don't bleed into the rest of the file
	if C.enabled and "\033[" in shown and not shown.endswith(C.RESET):
		shown += C.RESET

	return shown


def note_text(project: Project, base: str = "") -> str:
	return note_display(note_of(project), base)


#
# Table
#


Painter = Callable[[str, int, str], str]

Line = tuple[str, list[str], str]


def render_table(
	lines: list[Line],
	segments: list[Segment],
	headers: Mapping[str, str],
	settings: Settings,
	paint: Painter,
	*,
	shrinkable: Iterable[str] = SHRINKABLE,
	show_headers: bool = True,
	show_notes: bool = True,
	prefix: str = "",
	width: int = 0,
) -> list[str]:
	fields = fields_of(segments)
	aligns = [align for kind, _, align in segments if kind == "field"]

	if not fields:
		return ["no valid columns configured"]

	separator = column_separator(settings)
	horizontal: str = settings["display"]["horizontal_separator"]

	note_position: str = settings["display"]["note_position"]
	note_minimum: int = max(MINIMUM_NOTE, int(settings.get("display.note_min_width", 24)))

	widths = [
		max(
			len(headers[field]) if show_headers else 0,
			*(visible_length(values[index]) for _, values, _ in lines),
		)
		for index, field in enumerate(fields)
	]

	literals = sum(len(literal) for kind, literal, _ in segments if kind == "literal")

	available = width - len(prefix) if width else 0

	_shrink(fields, widths, literals, available, shrinkable)

	for _, values, _ in lines:
		for index, value in enumerate(values):
			values[index] = truncate(value, widths[index])

	def compose(
		cells: list[str],
		render: Callable[[str, int], str],
		parts: list[Segment] | None = None,
	) -> str:
		pieces: list[str] = []
		position = 0

		for kind, literal, _ in parts if parts is not None else segments:
			if kind == "literal":
				pieces.append(literal)
				continue

			pieces.append(render(cells[position], position))
			position += 1

		return "".join(pieces)

	note_space = (
		available - sum(widths) - literals - len(separator) if available else 10**6
	)

	trailing = show_notes and "note" not in fields

	notes: dict[str, tuple[str, bool]] = {}

	for key, _, note in lines:
		if not trailing or not note:
			continue

		if note_position == "below":
			notes[key] = (note, False)
			continue

		if note_position == "inline":
			inline = note_space >= MINIMUM_NOTE
		else:
			inline = note_space >= note_minimum and visible_length(note) <= note_space

		notes[key] = (note, inline)

	inline_width = max(
		(
			min(visible_length(note), note_space)
			for note, inline in notes.values()
			if inline
		),
		default=0,
	)

	# A row ending on an empty column would leave its separator hanging there
	shortened = segments[:-1]

	if shortened and shortened[-1][0] == "literal":
		shortened = shortened[:-1]

	closing = segments[-1][0] == "field" and any(
		kind == "field" for kind, _, _ in shortened
	)

	rendered: list[str] = []

	if show_headers:
		labels = [headers[field] for field in fields]
		header = compose(
			labels,
			lambda value, index: pad(value, widths[index], aligns[index] == ">"),
		)

		if inline_width:
			header = f"{header}{separator}{pad(NOTE_HEADER, inline_width)}"

		rendered.append(prefix + f"{C.BOLD}{header.rstrip()}{C.RESET}")

		if horizontal.strip():
			bars = [horizontal * width_ for width_ in widths]
			rule = compose(bars, lambda value, _: value)

			if inline_width:
				rule = f"{rule}{separator}{horizontal * inline_width}"

			rendered.append(prefix + f"{C.GRAY}{rule.rstrip()}{C.RESET}")

	for key, values, _ in lines:
		note, inline = notes.get(key, ("", False))

		empty = closing and not values[-1].strip() and not (note and inline)

		line = compose(
			values,
			lambda value, index, owner=key: paint(
				owner, index, pad(value, widths[index], aligns[index] == ">")
			),
			shortened if empty else None,
		)

		if note and inline:
			shown = truncate(note, note_space)
			line = f"{line}{separator}{C.GRAY}{shown}{C.RESET}"

		rendered.append(prefix + line.rstrip())

		if note and not inline:
			indent = prefix + "    "
			wrap_width = (available - 4) if available else 0

			for piece in wrap(note, wrap_width) if wrap_width else [note]:
				rendered.append(f"{indent}{C.GRAY}{piece}{C.RESET}")

	return rendered


def _shrink(
	fields: list[str],
	widths: list[int],
	literals: int,
	available: int,
	shrinkable: Iterable[str] = SHRINKABLE,
) -> None:
	if not available:
		return

	wanted = tuple(shrinkable)

	while True:
		overflow = sum(widths) + literals - available

		if overflow <= 0:
			return

		candidates = [
			index
			for index, field in enumerate(fields)
			if field in wanted and widths[index] > MINIMUM_COLUMN
		]

		if not candidates:
			return

		widest = max(candidates, key=lambda index: widths[index])

		room = widths[widest] - MINIMUM_COLUMN
		widths[widest] -= min(room, overflow)


# noinspection shadowing-names
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

	segments = layout(settings)
	fields = fields_of(segments)

	projects = dict(items)

	lines = [
		(
			path,
			[
				cell(path, project, field, settings, temporary_ids.get(path, 0))
				for field in fields
			],
			note_text(project, "GRAY"),
		)
		for path, project in items
	]

	def paint(key: str, index: int, value: str) -> str:
		return colourise(value, fields[index], projects[key], settings)

	return render_table(
		lines,
		segments,
		FIELD_HEADERS,
		settings,
		paint,
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


def print_projects(
	projects: Projects,
	settings: Settings,
	options: dict[str, Any] | None = None,
) -> None:
	from tracker.core.selection import (
		filter_projects,
		pin_numbering,
		regex_projects,
		search_projects,
		sort_projects,
	)

	options = options or {}

	if not projects:
		print("no projects found")
		return

	ordered = sort_projects(projects, settings)

	selected = filter_projects(dict(ordered), settings["display"]["filter"])

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

	# The rows about to be printed are what a temporary ID points at
	numbering = pin_numbering([path for path, _ in items], settings)

	for line in render_rows(items, settings, numbering):
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
