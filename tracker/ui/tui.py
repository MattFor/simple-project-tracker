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

from tracker.config.defaults import BRANCHES
from tracker.config.settings import Settings
from tracker.core import models
from tracker.core.models import Project, Projects
from tracker.core.selection import sort_projects, visible_projects
from tracker.core.storage import load_data, save_data
from tracker.core.todos import (
	Todo,
	Todos,
	done_status,
	is_done,
	key_of,
	load_todos,
	new_status,
	new_todo,
	next_id,
	save_todos,
	set_field,
	sort_todos,
	stamp,
	status_counts,
	status_of,
	temporary_ids,
)
from tracker.core.todos import restore as restore_todos
from tracker.core.undo import restore
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

BRANCH_MESSAGES = {
	"current": "only the current branch",
	"local": "every local branch",
	"all": "local and remote branches, as of the last fetch",
}

BRANCH_FLAGS = {"local": "local branches", "all": "all branches"}

CTRL_UP = 0x110000
CTRL_DOWN = 0x110001

KEY_CAPABILITIES = (
	("kcuu1", curses.KEY_UP),
	("kcud1", curses.KEY_DOWN),
	("kcub1", curses.KEY_LEFT),
	("kcuf1", curses.KEY_RIGHT),
	("khome", curses.KEY_HOME),
	("kend", curses.KEY_END),
	("kpp", curses.KEY_PPAGE),
	("knp", curses.KEY_NPAGE),
	("kdch1", curses.KEY_DC),
	("kUP5", CTRL_UP),
	("kDN5", CTRL_DOWN),
)

KEY_SEQUENCES = {
	"[A": curses.KEY_UP,
	"[B": curses.KEY_DOWN,
	"[C": curses.KEY_RIGHT,
	"[D": curses.KEY_LEFT,
	"OA": curses.KEY_UP,
	"OB": curses.KEY_DOWN,
	"OC": curses.KEY_RIGHT,
	"OD": curses.KEY_LEFT,
	"[H": curses.KEY_HOME,
	"[F": curses.KEY_END,
	"[1~": curses.KEY_HOME,
	"[4~": curses.KEY_END,
	"[5~": curses.KEY_PPAGE,
	"[6~": curses.KEY_NPAGE,
	"[3~": curses.KEY_DC,
	"[1;5A": CTRL_UP,
	"[1;5B": CTRL_DOWN,
}

SGR = re.compile(r"\x1b\[([0-9;]*)m")

KEYS = (
	("↑ ↓  j k", "move"),
	("Ctrl+↑ Ctrl+↓", "previous / next project"),
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
	(", .", "scroll the detail pane up / down"),
	("b", "git branches: the current one / every local one / remote ones too"),
	("r", "reload the database"),
	("n", "new todo; on a project, one linked to it"),
	("x", "mark the todo done / open it again"),
	("p i", "set the status / the note"),
	("m del", "rename / remove the todo"),
	("u", "undo the last change to the projects or the todos"),
	("@", "link: @ on one, then @ on a todo or project to link the two"),
	("o", "go to the project the todo is about, or the project's todo"),
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
	("n x p i", "edit"),
	("@ o", "link"),
	(", .", "scroll details"),
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


@dataclass
class Prompt:
	label: str
	text: str
	then: Callable[[str], None]
	hint: str = ""
	at: int = 0


def home_relative(path: str) -> str:
	home = os.path.expanduser("~")

	return "~" + path[len(home) :] if path == home or path.startswith(home + os.sep) else path


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
	folders = sorted((c for c in node.children.values() if c.children), key=lambda c: c.name.casefold())

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
		if (status is None or project.get("status") == status) and matches(path, project, query)
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


def edit_line(text: str, at: int, key: int) -> tuple[str, int]:
	if key in (curses.KEY_BACKSPACE, 127, 8):
		return (text[: at - 1] + text[at:], at - 1) if at else (text, at)

	if key == curses.KEY_DC:
		return text[:at] + text[at + 1 :], at

	if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
		return text, max(0, min(len(text), at + (1 if key == curses.KEY_RIGHT else -1)))

	if key in (curses.KEY_HOME, 1):
		return text, 0

	if key in (curses.KEY_END, 5):
		return text, len(text)

	# ^u and ^w, as in a shell
	if key in (21, 23):
		head = re.sub(r"\S*\s*$", "", text[:at]) if key == 23 else ""
		return head + text[at:], len(head)

	if 32 <= key < 0x110000 and chr(key).isprintable():
		return text[:at] + chr(key) + text[at:], at + 1

	return text, at


def mention_of(path: str, projects: Projects) -> str:
	name = os.path.basename(path)
	tokens = (f"@{name}", f"@({name})", f"@{projects[path].get('id')}")

	return next(
		(t for t in tokens if mentions.MENTION.fullmatch(t) and mentions.points_at(t, projects) == [path]),
		tokens[-1],
	)


def cycle(options: list[str], current: str | None) -> str | None:
	sequence: list[str | None] = [None, *options]

	if current not in sequence:
		return None

	return sequence[(sequence.index(current) + 1) % len(sequence)]


def details_of(node: Node, settings: Settings, tid: int = 0) -> list[str]:
	buffer = io.StringIO()

	with redirect_stdout(buffer):
		# Unwrapped, the pane wraps to its own width
		if node.todo is not None:
			print_todo(node.todo, settings, tid, width=0)
		elif node.project is not None:
			print_details(node.path, node.project, settings, width=0)

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


def cut(parts: list[tuple[str, int]], start: int, end: int) -> list[tuple[str, int]]:
	kept: list[tuple[str, int]] = []
	position = 0

	for text, attr in parts:
		low, high = max(start, position), min(end, position + len(text))

		if low < high:
			kept.append((text[low - position : high - position], attr))

		position += len(text)

	return kept


def fold(line: str, width: int) -> list[list[tuple[str, int]]]:
	parts = segments(line)
	plain = "".join(text for text, _ in parts)

	if len(plain) <= width or width < 2:
		return [parts]

	# A field's value carries on under itself, anything else under its first word
	hang = re.match(r"\s*\S.*?\s{2,}(?=\S)", plain)
	indent = min(len(hang.group(0)) if hang else len(plain) - len(plain.lstrip()), width // 2)

	rows: list[list[tuple[str, int]]] = []
	start = 0

	while start < len(plain):
		room = width - (indent if rows else 0)
		end = min(len(plain), start + room)
		space = plain.rfind(" ", start + (1 if rows else indent + 1), end + 1) if end < len(plain) else -1
		end = space if space > 0 else end

		rows.append(([(" " * indent, curses.A_NORMAL)] if rows else []) + cut(parts, start, end))
		start = end

		while start < len(plain) and plain[start] == " ":
			start += 1

	return rows


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


def put_parts(screen: curses.window, y: int, x: int, parts: list[tuple[str, int]], width: int) -> int:
	end = x + width

	for text, attr in parts:
		if x >= end:
			break

		x = put(screen, y, x, text[: end - x], attr)

	return x


def watched(settings: Settings) -> list[str]:
	return [os.path.abspath(os.path.expanduser(path)) for path in settings["daemon"]["paths"]]


def terminal_keys() -> dict[str, int]:
	keys = KEY_SEQUENCES.copy()

	for capability, code in KEY_CAPABILITIES:
		sequence = curses.tigetstr(capability)

		if sequence:
			value = sequence.decode("latin-1")
			keys[value.removeprefix("\x1b")] = code

	return keys


def read_key(screen: curses.window, keys: dict[str, int]) -> int:
	pressed = screen.get_wch()

	if not isinstance(pressed, str) or pressed != "\x1b":
		return ord(pressed) if isinstance(pressed, str) else pressed

	sequence = ""
	consumed: list[str | int] = []
	screen.timeout(25)

	try:
		while True:
			try:
				part = screen.get_wch()
			except curses.error:
				break

			consumed.append(part)

			if isinstance(part, int):
				break

			sequence += part

			if sequence in keys:
				return keys[sequence]

			if not any(candidate.startswith(sequence) for candidate in keys):
				break
	finally:
		screen.timeout(IDLE_MS)

	for part in reversed(consumed):
		if isinstance(part, str):
			curses.unget_wch(part)
		else:
			curses.ungetch(part)

	return 27


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
		self.prompt: Prompt | None = None
		self.message = ""
		self.linking: Node | None = None
		self.todos = load_todos(settings)
		self.tids = temporary_ids(self.todos, settings)
		mentions.use_todos(self.todos)
		self.rebuild()

	def run(self, screen: curses.window) -> None:
		_ = curses.curs_set(0)
		curses.use_default_colors()
		screen.keypad(False)
		keys = terminal_keys()

		for number in range(min(curses.COLORS, 16)):
			curses.init_pair(number + 1, number, -1)

		screen.timeout(IDLE_MS)

		while True:
			self.draw(screen)

			try:
				key = read_key(screen, keys)
			except curses.error:
				self.load_selected(screen)
				continue

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
			self.rows = [(0, Node(str(todo.get("name", "")), key, todo=todo)) for key, todo in picked]
		else:
			self.rebuild_projects()

		paths = [row.path for _, row in self.rows]

		if keep in paths:
			self.cursor = paths.index(keep)
		else:
			self.cursor = max(0, min(self.cursor, len(self.rows) - 1))

	def rebuild_projects(self) -> None:
		pool = pick(self.projects, self.settings, every=self.every)
		self.counts = Counter(str(project.get("status", "unknown")) for _, project in pool)
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
		self.message = ""

		if self.prompt is not None:
			self.prompt_key(key)
		elif self.typing:
			self.type_key(key)
		elif self.reading is not None:
			self.read_key(key)
		elif key == ord("q") or (key == 27 and not (self.query or self.status or self.linking)):
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
			CTRL_UP: lambda: self.jump_project(-1),
			CTRL_DOWN: lambda: self.jump_project(1),
			ord("."): lambda: self.scroll_pane(1),
			ord(","): lambda: self.scroll_pane(-1),
			ord("e"): self.expand_all,
			ord("c"): self.collapse_all,
			ord("s"): self.next_sort,
			ord("f"): self.next_status,
			ord("r"): self.reload,
			ord("\t"): self.switch,
			ord("/"): self.start_search,
			ord("?"): lambda: self.read(HELP),
			ord("n"): self.add,
			ord("x"): self.toggle_done,
			ord("p"): lambda: self.edit("status"),
			ord("i"): lambda: self.edit("note"),
			ord("m"): lambda: self.edit("name"),
			curses.KEY_DC: self.remove,
			ord("u"): self.undo,
			ord("@"): self.link,
			ord("o"): self.follow,
			ord("b"): self.next_branches,
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

	def prompt_key(self, key: int) -> None:
		prompt = self.prompt

		if prompt is None:
			return

		if key in (10, 13, curses.KEY_ENTER):
			self.prompt = None
			prompt.then(prompt.text)
		elif key == 27:
			self.prompt = None
		else:
			prompt.text, prompt.at = edit_line(prompt.text, prompt.at, key)

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

	def jump_project(self, direction: int) -> None:
		if self.todo_mode:
			self.move(self.cursor + direction)
			return

		index = self.cursor + direction

		while 0 <= index < len(self.rows):
			if self.rows[index][1].project is not None:
				self.move(index)
				return

			index += direction

	def scroll_pane(self, step: int) -> None:
		self.pane_scroll = max(0, self.pane_scroll + step)

	def next_branches(self) -> None:
		shown = BRANCHES[(BRANCHES.index(self.settings["output"]["branches"]) + 1) % len(BRANCHES)]
		self.settings = self.settings.override("output.branches", shown)
		self.details.clear()
		self.message = BRANCH_MESSAGES[shown]

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
		self.linking = None
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

	#
	# Editing
	#

	def ask(self, label: str, text: str, then: Callable[[str], None], hint: str = "") -> None:
		self.prompt = Prompt(label, text, then, hint, len(text))

	def saved(self, write: Callable[[], bool], done: str, failed: str = "could not save") -> None:
		buffer = io.StringIO()

		# Storage reports its errors on stdout, which would land over the screen
		with redirect_stdout(buffer):
			ok = write()

		self.message = done if ok else next(iter(buffer.getvalue().strip().splitlines()), failed)
		self.reload()

	def change(self, node: Node, field: str, value: str, done: str = "") -> None:
		entry = node.todo if node.todo is not None else node.project
		value = value if field == "note" else value.strip()

		if entry is None:
			return

		if field != "note" and not value:
			self.message = f"the {field} cannot be empty"
			return

		if str(entry.get(field, "")) == value:
			self.message = "nothing changed"
			return

		if node.todo is not None:
			set_field(node.todo, field, value, self.settings)
			self.saved(lambda: save_todos(self.todos, self.settings), done or f"{field} of {node.name} set")
		elif node.project is not None:
			models.set_field(node.project, field, value)
			self.saved(
				lambda: save_data(self.projects, self.settings, undoable=True),
				done or f"{field} of {node.name} set",
			)

	def edit(self, field: str) -> None:
		node = self.selected()
		entry = None if node is None else node.todo if node.todo is not None else node.project

		# A project's name is its folder
		if node is None or entry is None or (field == "name" and node.todo is None):
			return

		hint = " ".join(sorted(self.counts)) if field == "status" else ""

		self.ask(field, str(entry.get(field, "")), lambda value: self.change(node, field, value), hint)

	def toggle_done(self) -> None:
		node = self.selected()

		if node is None or node.todo is None:
			return

		done = is_done(node.todo, self.settings)
		self.change(node, "status", new_status(self.settings) if done else done_status(self.settings))

	def add(self) -> None:
		node = self.selected()
		about = node.path if node is not None and node.project is not None else None
		hint = f"linked to {node.name}" if node is not None and about else ""

		self.ask("new todo", "", lambda name: self.create(name, about), hint)

	def create(self, name: str, about: str | None) -> None:
		if not name.strip():
			return

		todo = new_todo(
			name.strip(),
			status=new_status(self.settings),
			note=mention_of(about, self.projects) if about else "",
			todo_id=next_id(self.todos),
			created=stamp(self.settings),
		)
		key = key_of(todo)
		self.todos[key] = todo

		self.saved(lambda: save_todos(self.todos, self.settings), f"added #{key} {todo['name']}")

		if self.todo_mode:
			self.focus(key, todo=True)

	def remove(self) -> None:
		node = self.selected()

		if node is None or node.todo is None:
			return

		del self.todos[node.path]
		self.saved(lambda: save_todos(self.todos, self.settings), f"removed {node.name}, u to undo")

	def undo(self) -> None:
		undone = restore_todos if self.todo_mode else restore

		self.saved(lambda: undone(self.settings) is not None, "undone", "nothing to undo")

	def link(self) -> None:
		node = self.selected()

		if node is None or not node.described():
			return

		start = self.linking
		if start is None or (start.todo is None) == (node.todo is None):
			# Over to the other side, to pick what it links to
			self.linking = node
			self.todo_mode = node.todo is None
			self.status = None
			self.pane_scroll = 0
			self.rebuild()
			self.message = f"@ on a {'todo' if self.todo_mode else 'project'} to link {node.name}, esc to cancel"
			return

		todo, project = (node, start) if node.todo is not None else (start, node)
		self.linking = None

		if todo.todo is None or project.path in mentions.about(todo.todo, self.projects):
			self.message = f"{todo.name} is already about {project.name}"
			return

		note = f"{todo.todo.get('note', '') or ''} {mention_of(project.path, self.projects)}".strip()
		self.change(todo, "note", note, f"linked {todo.name} to {project.name}")

	def follow(self) -> None:
		node = self.selected()

		if node is not None and node.todo is not None:
			paths = mentions.about(node.todo, self.projects)

			if paths:
				self.focus(paths[0], todo=False)
			else:
				self.message = f"{node.name} is about no project, @ links one"
		elif node is not None and node.project is not None:
			todos = sort_todos(mentions.todos_about(node.path, self.settings), self.settings)

			if todos:
				self.focus(todos[0][0], todo=True)
			else:
				self.message = f"no todo is about {node.name}, n adds one"

	def focus(self, key: str, *, todo: bool) -> None:
		self.todo_mode = todo
		self.query = ""
		self.status = None
		self.pane_scroll = 0

		if not todo:
			self.every = self.every or key not in dict(pick(self.projects, self.settings))
			self.collapsed = {path for path in self.collapsed if not under(key, path)}

		self.rebuild()

		paths = [node.path for _, node in self.rows]

		if key in paths:
			self.move(paths.index(key))

	def describe(self, node: Node) -> list[str]:
		lines = details_of(node, self.settings, self.tids.get(node.path, 0))
		named = mentions.named_after(node.todo, self.projects) if node.todo is not None else None

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
			rows = [row for line in self.reading for row in fold(line, width - 2)]
			self.scroll = min(self.scroll, max(0, len(rows) - body))

			for y, parts in enumerate(rows[self.scroll : self.scroll + body], 1):
				_ = put_parts(screen, y, 1, parts, width - 2)

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
			parts.append((f" {status} {count} ", colour_attr(status_colour(status, palette))))

		flags = [
			"every project" if self.every and not self.todo_mode else "",
			"flat" if self.flat and not self.todo_mode else "",
			f"sort {self.sort.replace('_', ' ')}" if self.sort else "",
			f"status {self.status}" if self.status else "",
			f"/{self.query}" if self.query and not self.typing else "",
			f"linking {self.linking.name}" if self.linking else "",
			BRANCH_FLAGS.get(self.settings["output"]["branches"], ""),
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
		elif self.prompt is not None:
			prompt = self.prompt
			label = f" {prompt.label}: "
			# Keep the cursor on screen in a long note
			start = max(0, prompt.at - (width - len(label) - 4))
			text, at = prompt.text[start:], prompt.at - start
			parts = [
				(label, colour_attr("bold yellow")),
				(text[:at], curses.A_BOLD),
				(text[at : at + 1] or " ", curses.A_BOLD | curses.A_REVERSE),
				(text[at + 1 :], curses.A_BOLD),
				(f"  {prompt.hint}" if prompt.hint else "", curses.A_DIM),
			]
		elif self.message:
			parts = [(f" {self.message}", colour_attr("cyan"))]
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

		statuses = [str((n.project or n.todo or {}).get("status", "")) for _, n in self.rows]
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
				[(text, attr | base) for (text, _), attr in zip(right, attrs, strict=True)],
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

		lines = self.details.get(node.path, ["\x1b[2m…\x1b[0m"]) if node.described() else self.folder_summary(node)

		room = width - left - 3
		rows = [row for line in lines for row in fold(line, room)]
		# The last line says there is more, when there is
		shown = body - 1 if len(rows) > body else body
		self.pane_scroll = min(self.pane_scroll, max(0, len(rows) - shown))

		for y, parts in enumerate(rows[self.pane_scroll : self.pane_scroll + shown], 1):
			_ = put_parts(screen, y, left + 2, parts, room)

		if shown < body:
			below = len(rows) - self.pane_scroll - shown
			more = f"↓ {below} more, J to scroll" if below else "↑ K to scroll back"

			_ = put(screen, body, left + 2, more[:room], colour_attr("cyan"))

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
