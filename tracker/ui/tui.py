import curses
import io
import locale
import os
import re
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import redirect_stdout, suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import final

from tracker.config.settings import Settings
from tracker.core.models import Project, Projects
from tracker.core.selection import sort_projects, visible_projects
from tracker.core.storage import load_data
from tracker.core.todos import (
	Todo,
	Todos,
	is_done,
	load_todos,
	sort_todos,
	status_counts,
	status_of,
	temporary_ids,
)
from tracker.ui import mentions
from tracker.ui.ansi import C
from tracker.ui.details import print_details
from tracker.ui.render import status_colour, timestamp
from tracker.ui.todos import FROM_PROJECT, note_of, print_todo
from tracker.ui.todos import view as todo_view
from tracker.util.text import parse_time

ELSEWHERE = "elsewhere"

COLOURS = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")

PANE_MIN_WIDTH = 100

IDLE_MS = 150

SORTS = {
	"name": "ascending",
	"status": "ascending",
	"last_touched": "descending",
	"last_used": "descending",
	"id": "ascending",
}

SGR = re.compile(r"\x1b\[([0-9;]*)m")

KEYS = (
	("↑ ↓  j k", "move"),
	("PgUp PgDn  ^u ^d", "a page / half a page"),
	("g G  Home End", "first / last row"),
	("← →  h l", "fold / unfold; → on a project opens it"),
	("space", "fold or unfold the folder"),
	("enter", "the project's details, full screen"),
	("[ ]", "previous / next folder"),
	("e c", "expand the full tree / collapse to the top folders"),
	("a", "every tracked project / only what display.filter shows"),
	("t", "tree / flat list"),
	("tab", "projects / todos and the projects they mention"),
	("/", "search names, paths and notes; enter keeps it, esc drops it"),
	("f", "show one status at a time"),
	("s", "next sort order"),
	("d", "detail pane on / off"),
	("J K", "scroll the detail pane"),
	("r", "reload the database"),
	("esc", "drop the search and status, or quit"),
	("?", "this help"),
	("q", "back, or quit"),
)

HELP = [
	"\x1b[1;35mKeys\x1b[0m",
	"",
	*(f"  \x1b[1;33m{keys.ljust(20)}\x1b[0m{what}" for keys, what in KEYS),
]

HINTS = (
	("?", "help"),
	("/", "search"),
	("a", "all"),
	("t", "flat"),
	("tab", "todos"),
	("e c", "expand/collapse"),
	("f", "status"),
	("s", "sort"),
	("q", "quit"),
)

READING_HINTS = (("↑↓", "scroll"), ("q", "back"))


@dataclass
class Node:
	name: str
	path: str
	project: Project | None = None
	children: dict[str, "Node"] = field(default_factory=dict)
	todo: Todo | None = None

	def described(self) -> bool:
		return self.project is not None or self.todo is not None

	def count(self) -> int:
		return (self.project is not None) + sum(c.count() for c in self.children.values())

	def projects(self) -> Iterator[Project]:
		if self.project is not None:
			yield self.project

		for child in self.children.values():
			yield from child.projects()


Row = tuple[int, Node]


def home_relative(path: str) -> str:
	home = os.path.expanduser("~")

	return (
		"~" + path[len(home) :]
		if path == home or path.startswith(home + os.sep)
		else path
	)


def under(path: str, root: str) -> bool:
	return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def build_tree(items: list[tuple[str, Project]], roots: list[str]) -> list[Node]:
	tops = {root: Node(home_relative(root), root) for root in roots}
	elsewhere = Node(ELSEWHERE, "")

	for path, project in items:
		root = max((r for r in roots if under(path, r)), key=len, default=None)

		if root is None:
			elsewhere.children[path] = Node(home_relative(path), path, project)
			continue

		node = tops[root]

		for part in os.path.relpath(path, root).split(os.sep):
			if part != ".":
				child = os.path.join(node.path, part)
				node = node.children.setdefault(child, Node(part, child))

		node.project = project

	return [node for node in (*tops.values(), elsewhere) if node.count()]


def ordered(node: Node) -> list[Node]:
	folders = sorted(
		(c for c in node.children.values() if c.children), key=lambda c: c.name.casefold()
	)

	return folders + [c for c in node.children.values() if not c.children]


def flatten(nodes: list[Node], collapsed: set[str], depth: int = 0) -> list[Row]:
	rows: list[Row] = []

	for node in nodes:
		rows.append((depth, node))

		if node.children and node.path not in collapsed:
			rows.extend(flatten(ordered(node), collapsed, depth + 1))

	return rows


def matches(path: str, project: Project, query: str) -> bool:
	needle = query.casefold()

	return needle in path.casefold() or needle in str(project.get("note", "")).casefold()


def pick(
	projects: Projects,
	settings: Settings,
	*,
	every: bool = False,
	sort: str | None = None,
	status: str | None = None,
	query: str = "",
) -> list[tuple[str, Project]]:
	if sort is not None:
		settings = settings.override("sorting.by", sort)
		settings = settings.override("sorting.direction", SORTS[sort])

	pool = projects if every else visible_projects(projects, settings)

	return [
		(path, project)
		for path, project in sort_projects(pool, settings)
		if (status is None or project.get("status") == status)
		and matches(path, project, query)
	]


def pick_todos(
	todos: Todos,
	settings: Settings,
	*,
	sort: str | None = None,
	status: str | None = None,
	query: str = "",
) -> list[tuple[str, Todo]]:
	if sort is not None:
		settings = settings.override("todos.sort", FROM_PROJECT[sort])
		settings = settings.override("todos.newest_first", SORTS[sort] == "descending")

	needle = query.casefold()

	return [
		(key, todo)
		for key, todo in sort_todos(todos, settings)
		if (status is None or status_of(todo) == status)
		and needle in f"{todo.get('name', '')}\n{note_of(todo)}".casefold()
	]


def cycle(options: list[str], current: str | None) -> str | None:
	sequence: list[str | None] = [None, *options]

	if current not in sequence:
		return None

	return sequence[(sequence.index(current) + 1) % len(sequence)]


def details_of(node: Node, settings: Settings, tid: int = 0) -> list[str]:
	buffer = io.StringIO()

	with redirect_stdout(buffer):
		if node.todo is not None:
			print_todo(node.todo, settings, tid)
		elif node.project is not None:
			print_details(node.path, node.project, settings)

	return buffer.getvalue().splitlines()


def colour_attr(name: str) -> int:
	words = name.lower().replace("-", "_").split()
	attr = curses.A_BOLD if "bold" in words else curses.A_NORMAL
	colour = words[-1] if words else ""
	bright = colour.startswith("bright_")
	colour = colour.removeprefix("bright_")

	if colour in ("gray", "grey"):
		return attr | curses.A_DIM

	if colour not in COLOURS or not curses.has_colors():
		return attr

	number = COLOURS.index(colour) + (8 if bright and curses.COLORS >= 16 else 0)

	return attr | curses.color_pair(number + 1) | (curses.A_BOLD if bright else 0)


def apply_sgr(attr: int, codes: str) -> int:
	for text in codes.split(";"):
		code = int(text) if text.isdigit() else 0

		if code == 0:
			attr = curses.A_NORMAL
		elif code == 1:
			attr |= curses.A_BOLD
		elif code in (2, 90):
			attr |= curses.A_DIM
		elif 30 <= code <= 37 or 91 <= code <= 97:
			name = ("bright_" if code > 90 else "") + COLOURS[code % 10]
			attr = (attr & ~curses.A_COLOR) | colour_attr(name)

	return attr


def segments(line: str) -> list[tuple[str, int]]:
	parts: list[tuple[str, int]] = []
	attr = curses.A_NORMAL
	position = 0

	for match in SGR.finditer(line):
		parts.append((line[position : match.start()], attr))
		attr = apply_sgr(attr, match.group(1))
		position = match.end()

	parts.append((line[position:], attr))

	return [(text, attr) for text, attr in parts if text]


def age_attr(value: str, settings: Settings) -> int:
	moment = parse_time(value, settings["display"]["time_format"])

	if moment is None:
		return curses.A_DIM

	days = (datetime.now(moment.tzinfo) - moment).days

	if days < 1:
		return colour_attr("bright_green")

	if days < 7:
		return colour_attr("green")

	if days < 30:
		return colour_attr("yellow")

	return curses.A_DIM


def put(screen: curses.window, y: int, x: int, value: str, attr: int = 0) -> int:
	with suppress(curses.error):
		screen.addstr(y, x, value, attr)

	return x + len(value)


def put_parts(
	screen: curses.window, y: int, x: int, parts: list[tuple[str, int]], width: int
) -> int:
	end = x + width

	for text, attr in parts:
		if x >= end:
			break

		x = put(screen, y, x, text[: end - x], attr)

	return x


def watched(settings: Settings) -> list[str]:
	return [
		os.path.abspath(os.path.expanduser(path)) for path in settings["daemon"]["paths"]
	]


@final
class Browser:
	def __init__(self, projects: Projects, settings: Settings) -> None:
		self.projects = projects
		self.settings = settings
		self.every = False
		self.flat = False
		self.pane = True
		self.sort: str | None = None
		self.status: str | None = None
		self.query = ""
		self.typing = False
		self.collapsed: set[str] = set()
		self.counts: Counter[str] = Counter()
		self.items: list[tuple[str, Project]] = []
		self.rows: list[Row] = []
		self.cursor = 0
		self.top = 0
		self.page = 10
		self.details: dict[str, list[str]] = {}
		self.reading: list[str] | None = None
		self.scroll = 0
		self.pane_scroll = 0
		self.todo_mode = False
		self.todos = load_todos(settings)
		self.tids = temporary_ids(self.todos, settings)
		mentions.use_todos(self.todos)
		self.rebuild()

	def run(self, screen: curses.window) -> None:
		_ = curses.curs_set(0)
		curses.set_escdelay(25)
		curses.use_default_colors()

		for number in range(min(curses.COLORS, 16)):
			curses.init_pair(number + 1, number, -1)

		screen.timeout(IDLE_MS)

		while True:
			self.draw(screen)

			try:
				pressed = screen.get_wch()
			except curses.error:
				self.load_selected(screen)
				continue

			key = ord(pressed) if isinstance(pressed, str) else pressed

			if not self.handle(key):
				return

	def rebuild(self) -> None:
		node = self.selected()
		keep = node.path if node else ""

		if self.todo_mode:
			self.counts = Counter(status_counts(self.todos))
			picked = pick_todos(
				self.todos,
				self.settings,
				sort=self.sort,
				status=self.status,
				query=self.query,
			)
			self.rows = [
				(0, Node(str(todo.get("name", "")), key, todo=todo))
				for key, todo in picked
			]
		else:
			self.rebuild_projects()

		paths = [row.path for _, row in self.rows]

		if keep in paths:
			self.cursor = paths.index(keep)
		else:
			self.cursor = max(0, min(self.cursor, len(self.rows) - 1))

	def rebuild_projects(self) -> None:
		pool = pick(self.projects, self.settings, every=self.every)
		self.counts = Counter(
			str(project.get("status", "unknown")) for _, project in pool
		)
		self.items = pick(
			self.projects,
			self.settings,
			every=self.every,
			sort=self.sort,
			status=self.status,
			query=self.query,
		)

		if self.flat:
			self.rows = [(0, Node(os.path.basename(p), p, pr)) for p, pr in self.items]
		else:
			tree = build_tree(self.items, watched(self.settings))
			self.rows = flatten(tree, self.collapsed)

	def selected(self) -> Node | None:
		return self.rows[self.cursor][1] if self.cursor < len(self.rows) else None

	def load_selected(self, screen: curses.window) -> None:
		node = self.selected()

		if node is None or not node.described() or node.path in self.details:
			return

		if self.pane and screen.getmaxyx()[1] >= PANE_MIN_WIDTH:
			self.details[node.path] = self.describe(node)

	def handle(self, key: int) -> bool:
		if self.typing:
			self.type_key(key)
		elif self.reading is not None:
			self.read_key(key)
		elif key == ord("q") or (key == 27 and not (self.query or self.status)):
			return False
		else:
			self.tree_key(key)

		return True

	def tree_key(self, key: int) -> None:
		half = max(1, self.page // 2)
		steps = {
			curses.KEY_UP: -1,
			ord("k"): -1,
			curses.KEY_DOWN: 1,
			ord("j"): 1,
			curses.KEY_PPAGE: -self.page,
			curses.KEY_NPAGE: self.page,
			21: -half,
			4: half,
		}
		toggles = {ord("a"): "every", ord("t"): "flat", ord("d"): "pane"}
		actions: dict[int, Callable[[], None]] = {
			curses.KEY_HOME: lambda: self.move(0),
			ord("g"): lambda: self.move(0),
			curses.KEY_END: lambda: self.move(len(self.rows) - 1),
			ord("G"): lambda: self.move(len(self.rows) - 1),
			ord("["): lambda: self.jump_folder(-1),
			ord("]"): lambda: self.jump_folder(1),
			ord("J"): lambda: self.scroll_pane(1),
			ord("K"): lambda: self.scroll_pane(-1),
			ord("e"): self.expand_all,
			ord("c"): self.collapse_all,
			ord("s"): self.next_sort,
			ord("f"): self.next_status,
			ord("r"): self.reload,
			ord("\t"): self.switch,
			ord("/"): self.start_search,
			ord("?"): lambda: self.read(HELP),
			27: self.clear_filters,
		}

		if key in steps:
			self.move(self.cursor + steps[key])
		elif key in toggles:
			setattr(self, toggles[key], not getattr(self, toggles[key]))
			self.rebuild()
		elif key in actions:
			actions[key]()
		else:
			self.node_key(key)

	def node_key(self, key: int) -> None:
		node = self.selected()

		if node is None:
			return

		foldable = bool(node.children) and not self.flat
		folded = node.path in self.collapsed

		if key == ord(" ") and foldable:
			self.toggle(node)
		elif key in (curses.KEY_LEFT, ord("h")):
			if foldable and not folded:
				self.toggle(node)
			else:
				self.move(self.parent_row())
		elif key in (curses.KEY_RIGHT, ord("l")) and foldable and folded:
			self.toggle(node)
		elif key in (curses.KEY_RIGHT, ord("l"), curses.KEY_ENTER, 10, 13):
			if node.described():
				self.open(node)
			elif foldable:
				self.toggle(node)

	def type_key(self, key: int) -> None:
		if key in (10, 13, curses.KEY_ENTER):
			self.typing = False
		elif key == 27:
			self.typing = False
			self.query = ""
		elif key in (curses.KEY_BACKSPACE, 127, 8):
			self.query = self.query[:-1]
		elif 32 <= key < 0x110000 and chr(key).isprintable():
			self.query += chr(key)
		else:
			return

		self.rebuild()

	def read_key(self, key: int) -> None:
		steps = {
			curses.KEY_UP: -1,
			ord("k"): -1,
			curses.KEY_DOWN: 1,
			ord("j"): 1,
			curses.KEY_PPAGE: -self.page,
			curses.KEY_NPAGE: self.page,
			ord("g"): -(10**9),
			ord("G"): 10**9,
		}

		if key in steps:
			self.scroll = max(0, self.scroll + steps[key])
		elif key in (ord("q"), ord("?"), 27, curses.KEY_LEFT, ord("h")):
			self.reading = None

	def move(self, index: int) -> None:
		index = max(0, min(index, len(self.rows) - 1))

		if index != self.cursor:
			self.pane_scroll = 0

		self.cursor = index

	def toggle(self, node: Node) -> None:
		self.collapsed ^= {node.path}
		self.rebuild()

	def parent_row(self) -> int:
		depth = self.rows[self.cursor][0]

		for index in range(self.cursor - 1, -1, -1):
			if self.rows[index][0] < depth:
				return index

		return self.cursor

	def jump_folder(self, direction: int) -> None:
		index = self.cursor + direction

		while 0 <= index < len(self.rows):
			if self.rows[index][1].children:
				self.move(index)
				return

			index += direction

	def scroll_pane(self, step: int) -> None:
		self.pane_scroll = max(0, self.pane_scroll + step)

	def expand_all(self) -> None:
		self.collapsed.clear()
		self.rebuild()

	def collapse_all(self) -> None:
		tree = flatten(build_tree(self.items, watched(self.settings)), set())
		self.collapsed = {node.path for depth, node in tree if depth and node.children}
		self.rebuild()

	def next_sort(self) -> None:
		self.sort = cycle(list(SORTS), self.sort)
		self.rebuild()

	def next_status(self) -> None:
		self.status = cycle(sorted(self.counts), self.status)
		self.rebuild()

	def start_search(self) -> None:
		self.typing = True

	def clear_filters(self) -> None:
		self.query = ""
		self.status = None
		self.rebuild()

	def switch(self) -> None:
		self.todo_mode = not self.todo_mode
		# The statuses of one are not the statuses of the other
		self.status = None
		self.pane_scroll = 0
		self.rebuild()

	def reload(self) -> None:
		self.projects = load_data(self.settings)
		self.todos = load_todos(self.settings)
		self.tids = temporary_ids(self.todos, self.settings)
		mentions.use(self.projects)
		mentions.use_todos(self.todos)
		self.details.clear()
		self.rebuild()

	def describe(self, node: Node) -> list[str]:
		lines = details_of(node, self.settings, self.tids.get(node.path, 0))
		named = (
			mentions.named_after(node.todo, self.projects)
			if node.todo is not None
			else None
		)

		# A todo named after its project carries that project's check view along
		if named is not None:
			project = Node(os.path.basename(named), named, self.projects[named])
			lines += ["", *details_of(project, self.settings)]

		return lines

	def open(self, node: Node) -> None:
		if node.path not in self.details:
			self.details[node.path] = self.describe(node)

		self.read(self.details[node.path])

	def palette(self) -> Settings:
		return todo_view(self.settings) if self.todo_mode else self.settings

	def read(self, lines: list[str]) -> None:
		self.reading = lines
		self.scroll = 0

	def draw(self, screen: curses.window) -> None:
		screen.erase()
		height, width = screen.getmaxyx()
		body = max(1, height - 2)
		self.page = body

		self.draw_header(screen, width)

		if self.reading is not None:
			self.scroll = min(self.scroll, max(0, len(self.reading) - body))

			for y, line in enumerate(self.reading[self.scroll : self.scroll + body], 1):
				_ = put_parts(screen, y, 1, segments(line), width - 2)

			self.draw_footer(screen, height - 1, width, READING_HINTS)
		else:
			pane = self.pane and width >= PANE_MIN_WIDTH
			tree_width = max(40, width * 45 // 100) if pane else width

			self.draw_rows(screen, body, tree_width)

			if pane:
				self.draw_pane(screen, body, tree_width, width)

			self.draw_footer(screen, height - 1, width, HINTS)

		screen.refresh()

	def draw_header(self, screen: curses.window, width: int) -> None:
		shown = len(self.rows) if self.todo_mode else len(self.items)
		total = sum(self.counts.values())
		palette = self.palette()
		parts = [
			(" tracker ", colour_attr("bold magenta") | curses.A_REVERSE),
			(f" {shown} of {total} " if shown != total else f" {total} ", curses.A_BOLD),
			("todos " if self.todo_mode else "projects ", curses.A_NORMAL),
		]

		for status, count in self.counts.most_common():
			parts.append(
				(f" {status} {count} ", colour_attr(status_colour(status, palette)))
			)

		flags = [
			"every project" if self.every and not self.todo_mode else "",
			"flat" if self.flat and not self.todo_mode else "",
			f"sort {self.sort.replace('_', ' ')}" if self.sort else "",
			f"status {self.status}" if self.status else "",
			f"/{self.query}" if self.query and not self.typing else "",
		]

		for flag in filter(None, flags):
			parts.append((f" [{flag}]", colour_attr("cyan")))

		_ = put_parts(screen, 0, 0, parts, width - 1)

	def draw_footer(
		self,
		screen: curses.window,
		y: int,
		width: int,
		hints: tuple[tuple[str, str], ...],
	) -> None:
		if self.typing:
			parts = [
				(" /", colour_attr("bold yellow")),
				(f"{self.query}▏", curses.A_BOLD),
			]
			parts.append(("  enter keep  esc drop", curses.A_DIM))
		else:
			parts: list[tuple[str, int]] = []

			for key, what in hints:
				parts.append((f" {key}", colour_attr("bold yellow")))
				parts.append((f" {what} ", curses.A_DIM))

		_ = put_parts(screen, y, 0, parts, width - 1)

	def draw_rows(self, screen: curses.window, body: int, width: int) -> None:
		if not self.rows:
			_ = put(screen, 2, 2, "nothing matches", curses.A_DIM)
			return

		self.top = min(max(self.top, self.cursor - body + 1), self.cursor)

		statuses = [
			str((n.project or n.todo or {}).get("status", "")) for _, n in self.rows
		]
		status_width = min(14, max((len(s) for s in statuses), default=0))
		palette = self.palette()

		for y, (depth, node) in enumerate(self.rows[self.top : self.top + body], 1):
			base = curses.A_REVERSE if self.top + y - 1 == self.cursor else 0
			label = [(text, attr | base) for text, attr in self.label(depth, node)]

			_ = put(screen, y, 0, " " * width, base)

			if node.todo is not None:
				status = status_of(node.todo)
				value = node.todo.get("updated") or node.todo.get("created") or "unknown"
			elif node.project is not None:
				status = str(node.project.get("status", "unknown"))
				value = str(node.project.get("last_touched", "unknown"))
			else:
				_ = put_parts(screen, y, 0, label, width)
				continue

			status = status[:status_width]
			touched = timestamp(value, self.settings)[:9].rjust(9)
			right = [
				(f" {status.ljust(status_width)}", status_colour(status, palette)),
				(f"  {touched} ", ""),
			]
			attrs = [colour_attr(right[0][1]), age_attr(value, self.settings)]
			name_width = max(1, width - sum(len(text) for text, _ in right))

			_ = put_parts(screen, y, 0, label, name_width)
			_ = put_parts(
				screen,
				y,
				name_width,
				[
					(text, attr | base)
					for (text, _), attr in zip(right, attrs, strict=True)
				],
				width - name_width,
			)

	def label(self, depth: int, node: Node) -> list[tuple[str, int]]:
		indent = ("  " * depth, curses.A_DIM)

		if node.todo is not None:
			done = is_done(node.todo, self.settings)
			parts = [(f" {node.name}", curses.A_DIM if done else curses.A_BOLD)]

			for path, project in mentions.projects_of(node.todo, self.settings):
				colour = status_colour(status_of(project), self.settings)
				parts.append((f"  @{os.path.basename(path)}", colour_attr(colour)))

			note = note_of(node.todo).splitlines()

			return [*parts, *([(f"  {note[0]}", curses.A_DIM)] if note else [])]

		if self.flat:
			where = home_relative(os.path.dirname(node.path))
			return [
				indent,
				(f" {node.name}", curses.A_BOLD),
				(f"  {where}", curses.A_DIM),
			]

		if not node.children:
			return [indent, (f"  {node.name}", curses.A_NORMAL)]

		marker = "▸ " if node.path in self.collapsed else "▾ "
		colour = colour_attr("bold magenta" if depth == 0 else "bold blue")

		return [
			indent,
			(marker, curses.A_DIM),
			(node.name, colour),
			(f"  {node.count()}", curses.A_DIM),
		]

	def draw_pane(self, screen: curses.window, body: int, left: int, width: int) -> None:
		for y in range(1, body + 1):
			_ = put(screen, y, left, "│", curses.A_DIM)

		node = self.selected()

		if node is None:
			return

		if node.described():
			lines = self.details.get(node.path, ["\x1b[2m…\x1b[0m"])
		else:
			lines = self.folder_summary(node)

		self.pane_scroll = min(self.pane_scroll, max(0, len(lines) - body))
		visible = lines[self.pane_scroll : self.pane_scroll + body]

		for y, line in enumerate(visible, 1):
			_ = put_parts(screen, y, left + 2, segments(line), width - left - 3)

	def folder_summary(self, node: Node) -> list[str]:
		counts = Counter(str(p.get("status", "unknown")) for p in node.projects())
		where = home_relative(node.path)
		total = node.count()
		lines = [
			f"{C.BOLD}{C.BLUE}{node.name}{C.RESET}",
			*([f"{C.GRAY}{where}{C.RESET}"] if where != node.name else []),
			"",
			f"{C.BOLD}{total} project{'' if total == 1 else 's'}{C.RESET}",
		]

		for status, count in counts.most_common():
			painted = C.paint(status.ljust(16), status_colour(status, self.settings))
			lines.append(f"  {painted}{count}")

		return lines


def run(projects: Projects, settings: Settings) -> int:
	browser = Browser(projects, settings)

	if not browser.items:
		print("no projects found")
		return 0

	_ = locale.setlocale(locale.LC_ALL, "")

	curses.wrapper(browser.run)

	return 0
