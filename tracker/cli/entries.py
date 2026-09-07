import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, ClassVar

from tracker.config.settings import Settings
from tracker.core.entries import (
	ALL_SELECTORS,
	Space,
	pin_entries,
	resolve_selection,
	status_counts,
	temporary_ids,
)
from tracker.core.models import Projects
from tracker.ui.ansi import C
from tracker.ui.ask import confirm as ask
from tracker.ui.render import note_display, status_colour

Entries = dict[str, Any]

EVERYTHING = ("all", "a", "*")


@dataclass
class Context:
	settings: Settings
	data: Projects
	verbose: bool = False
	assume_yes: bool = False
	options: dict[str, Any] = field(default_factory=dict)
	pending: bool = False

	def log(self, message: str) -> None:
		if self.verbose:
			print(f"{C.GRAY}[verbose] {message}{C.RESET}")

	def save(self, *, undoable: bool = True) -> bool:
		from tracker.core.storage import save_data

		self.pending = False

		return save_data(self.data, self.settings, undoable=undoable)

	def temporary_ids(self) -> dict[str, int]:
		from tracker.core.selection import temporary_ids as numbering

		return numbering(self.data, self.settings)

	def pin(self, projects: Projects) -> dict[str, int]:
		from tracker.core.selection import pin_projects

		return pin_projects(projects, self.settings)

	def mark_used(self, selected: Projects) -> bool:
		if not selected or not self.settings["projects"]["track_usage"]:
			return False

		stamp = time.strftime(self.settings["display"]["time_format"])

		for project in selected.values():
			project["last_used"] = stamp
			project["uses"] = int(project.get("uses", 0)) + 1

		self.pending = True

		return True

	def select(self, selectors: list[str], *, quiet: bool = False) -> Projects:
		from tracker.core.selection import select_projects

		selected = select_projects(self.data, self.settings, selectors, quiet=quiet)

		_ = self.mark_used(selected)

		return selected


Handler = Callable[[Context, list[str]], int]


def marks_used(handler: Handler) -> Handler:
	@wraps(handler)
	def wrapper(context: Context, args: list[str]) -> int:
		status = handler(context, args)

		if context.pending and not context.save(undoable=False):
			return 1

		return status

	return wrapper


def plural(count: int, word: str = "project") -> str:
	return f"{count} {word}{'s' if count != 1 else ''}"


def confirm(context: Context, question: str) -> bool:
	return ask(
		question,
		assume_yes=context.assume_yes,
		required=bool(context.settings["projects"]["confirm_destructive"]),
	)


def all_or_nothing(
	selected: Entries, unmatched: list[str], command: str, args: list[str]
) -> Entries | None:
	if unmatched:
		# Do not repeat a second error
		if len(args) > 1:
			print(f"[ERROR] {command} did nothing, unresolved: {', '.join(unmatched)}")
		else:
			print(f"{C.GRAY}        {command} did nothing{C.RESET}")

		return None

	return selected or None


def report_undo(
	before: Mapping[str, Any], after: Mapping[str, Any], noun: str, again: str
) -> None:
	from tracker.core.undo import differences

	added, removed, changed = differences(before, after)

	print(f"undone, {plural(len(after), noun)} tracked")

	parts = [
		f"{count} {word}"
		for count, word in ((added, "added"), (removed, "removed"), (changed, "changed"))
		if count
	]

	if parts:
		print(f"  {C.GRAY}{', '.join(parts)} back{C.RESET}")

	print(f"  {C.GRAY}{again} to put it back{C.RESET}")


def as_statuses(args: list[str]) -> list[str]:
	return [f"s:{arg}" for arg in args if ":" not in arg and "=" not in arg]


class Kind:
	space: ClassVar[Space]

	fields: ClassVar[Mapping[str, str]] = {}

	greedy: ClassVar[tuple[str, ...]] = ()
	required: ClassVar[tuple[str, ...]] = ()

	hints: ClassVar[tuple[tuple[str, str], ...]] = ()

	empty: ClassVar[str] = "nothing tracked yet"
	hint: ClassVar[str] = ""

	show_unused: ClassVar[bool] = False

	def load(self, context: Context) -> Entries:
		del context

		raise NotImplementedError

	def save(self, context: Context, entries: Entries) -> bool:
		del context, entries

		raise NotImplementedError

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
		del context, entries, numbering, prefix, headers, notes

		raise NotImplementedError

	def details(self, context: Context, key: str, entry: Any, tid: int) -> None:
		del context, key, entry, tid

		raise NotImplementedError

	def set(self, context: Context, entry: Any, name: str, value: str) -> None:
		del context, entry, name, value

		raise NotImplementedError

	def listing(self, context: Context, args: list[str]) -> int:
		del context, args

		raise NotImplementedError

	def used(self, context: Context, selected: Entries) -> None:
		"""Looking at something may be worth remembering."""

		del context, selected

	def suggest(self, args: list[str]) -> None:
		"""A word that matched nothing may have been meant as a command."""

		del args

	def note(self, text: str, context: Context, base: str = "") -> str:
		del context

		return note_display(text, base)

	#
	# What they share
	#

	@property
	def editable(self) -> tuple[str, ...]:
		return tuple(dict.fromkeys(self.fields.values()))

	def numbering(self, context: Context, entries: Entries) -> dict[str, int]:
		return temporary_ids(entries, context.settings, self.space)

	def pin(self, context: Context, entries: Entries) -> dict[str, int]:
		return pin_entries(entries, context.settings, self.space)

	def missing(self, command: str) -> int:
		print(f"[ERROR] {command} requires a {self.space.noun}")

		if self.hint:
			print(f"{C.GRAY}        {self.hint}{C.RESET}")

		return 1

	def resolve(
		self,
		context: Context,
		entries: Entries,
		selectors: list[str],
		*,
		quiet: bool = False,
	) -> tuple[Entries, list[str]]:
		selected, unmatched = resolve_selection(
			entries, context.settings, selectors, self.space, quiet=quiet
		)

		self.used(context, selected)

		return selected, unmatched

	def chosen(
		self, context: Context, entries: Entries, args: list[str], command: str
	) -> Entries | None:
		selected, unmatched = self.resolve(context, entries, args)

		return all_or_nothing(selected, unmatched, command, args)

	def one_row(
		self, context: Context, entries: Entries, numbering: dict[str, int]
	) -> str:
		lines = self.rows(context, entries, numbering, notes=False)

		return lines[0] if lines else ""

	#
	# The commands
	#

	def check(self, context: Context, args: list[str]) -> int:
		if not args:
			return self.missing("check")

		entries = self.load(context)
		selected, _ = self.resolve(context, entries, args)

		if not selected:
			return 1

		numbering = self.pin(context, selected)

		for index, (key, entry) in enumerate(self.space.sort(selected, context.settings)):
			if index:
				print()

			self.details(context, key, entry, numbering.get(key, 0))

		return 0

	def show(self, context: Context, args: list[str]) -> int:
		entries = self.load(context)

		if not args:
			return self.listing(context, [])

		if len(args) == 1 and args[0].lower() in ALL_SELECTORS:
			return self.listing(context, ["all"])

		selected, unmatched = self.resolve(context, entries, args, quiet=True)

		if not selected:
			# A word that names nothing may be a status
			selected, _ = self.resolve(context, entries, as_statuses(args), quiet=True)
			unmatched = []

		if not selected:
			_ = self.resolve(context, entries, args)

			self.suggest(args)

			return 1

		if unmatched:
			_ = self.resolve(context, entries, unmatched)

		numbering = self.pin(context, selected)

		if len(selected) == 1:
			key, entry = next(iter(selected.items()))

			self.details(context, key, entry, numbering.get(key, 0))

			return 0

		for line in self.rows(context, selected, numbering):
			print(line)

		return 0

	def remove(self, context: Context, args: list[str]) -> int:
		if not args:
			return self.missing("remove")

		entries = self.load(context)

		if args[0].lower().strip("-") in EVERYTHING:
			return self._remove_all(context, entries)

		selected = self.chosen(context, entries, args, "remove")

		if selected is None:
			return 1

		count = plural(len(selected), self.space.noun)

		if len(selected) > 1 and not confirm(context, f"remove {count}?"):
			print("cancelled")
			return 1

		lines = self.rows(
			context, selected, self.numbering(context, entries), prefix="  "
		)

		for key in selected:
			del entries[key]

		if not self.save(context, entries):
			return 1

		if len(selected) == 1:
			print(f"removed {lines[0].strip()}")

			return 0

		print(f"removed {count}")

		for line in lines:
			print(line)

		return 0

	def _remove_all(self, context: Context, entries: Entries) -> int:
		if not entries:
			print(f"no {self.space.plural} to remove")
			return 0

		count = len(entries)

		if not confirm(context, f"remove all {plural(count, self.space.noun)}?"):
			print("cancelled")
			return 1

		entries.clear()

		if not self.save(context, entries):
			return 1

		print(f"removed {count} entries")

		return 0

	def fields_from(self, args: list[str]) -> list[tuple[str, str]] | None:
		wanted: list[tuple[str, str]] = []
		index = 0

		while index < len(args):
			name = self.fields.get(args[index].lower().strip("-"), "")

			if not name:
				known = ", ".join(self.editable)

				print(f"[ERROR] unknown field '{args[index]}', expected one of: {known}")
				return None

			if name in self.greedy:
				value = " ".join(args[index + 1 :])
				index = len(args)
			else:
				if index + 1 >= len(args):
					print(f"[ERROR] edit {name} requires a value")
					return None

				value = args[index + 1]
				index += 2

			if name in self.required and not value.strip():
				print(f"[ERROR] edit {name} requires a value")
				return None

			wanted.append((name, value.strip() if name in self.required else value))

		return wanted

	def edit(self, context: Context, args: list[str]) -> int:
		if not args:
			return self.missing("edit")

		if len(args) < 2:
			print(f"[ERROR] edit requires a field: {', '.join(self.editable)}")
			return 1

		entries = self.load(context)
		selected = self.chosen(context, entries, [args[0]], "edit")

		if selected is None:
			return 1

		wanted = self.fields_from(args[1:])

		if wanted is None:
			return 1

		return self.write(context, entries, selected, wanted)

	def write(
		self,
		context: Context,
		entries: Entries,
		selected: Entries,
		wanted: list[tuple[str, str]],
	) -> int:
		changes: dict[str, tuple[str, str]] = {}
		changed: Entries = {}

		for key, entry in selected.items():
			for name, value in wanted:
				old = str(entry.get(name, ""))

				if old == value:
					continue

				self.set(context, entry, name, value)

				changed[key] = entry

				if len(selected) == 1:
					changes[name] = (old, value)

		if not changed:
			if len(selected) > 1:
				count = plural(len(selected), self.space.noun)
				print(f"nothing changed, all {count} already matched")
			else:
				print("nothing changed")

			return 0

		if not self.save(context, entries):
			return 1

		numbering = self.numbering(context, entries)

		if len(selected) > 1:
			untouched = len(selected) - len(changed)
			skipped = f", {untouched} already matched" if untouched else ""

			print(f"edited {plural(len(changed), self.space.noun)}{skipped}")

			for line in self.rows(context, changed, numbering, prefix="  "):
				print(line)

			return 0

		print(f"edited {self.one_row(context, changed, numbering)}")

		empty = '""'

		for name, (old, new) in changes.items():
			if name == "note":
				was = self.note(old, context, "GRAY") if old else empty
				now = self.note(new, context) if new else empty
			else:
				was, now = old or empty, new or empty

			print(f"  {name}: {C.GRAY}{was}{C.RESET} -> {now}")

		return 0

	def field(self, context: Context, args: list[str], name: str) -> int:
		if not args:
			return self.missing(name)

		if name in self.greedy:
			return self.edit(context, [args[0], name, *args[1:]])

		if len(args) < 2:
			print(f"[ERROR] {name} requires a value")
			return 1

		return self.edit(context, [args[0], name, " ".join(args[1:])])

	def statuses(self, context: Context) -> int:
		settings = context.settings
		counts = status_counts(self.load(context))

		if not counts:
			print(self.empty)
			return 0

		print(f"{C.BOLD}Statuses in use{C.RESET}")

		for status, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
			print(
				f"  {C.paint(status.ljust(16), status_colour(status, settings))}{count}"
			)

		if self.show_unused:
			configured = settings.get("display.status_colours", {})
			known = set(configured) if isinstance(configured, dict) else set()

			unused = sorted(known - set(counts))

			if unused:
				print(f"\n{C.BOLD}Configured but unused{C.RESET}")
				print(f"  {C.GRAY}{', '.join(unused)}{C.RESET}")

		if not self.hints:
			return 0

		width = max(len(command) for command, _ in self.hints) + 3

		print()

		for command, explanation in self.hints:
			print(f"{C.GRAY}{command.ljust(width)}{explanation}{C.RESET}")

		return 0
