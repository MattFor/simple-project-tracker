import os
import sys
import time

from typing import Any
from pathlib import Path
from functools import wraps
from collections.abc import Callable
from dataclasses import dataclass, field

from tracker.core import daemon
from tracker.config import paths
from tracker.config.writer import write_setting
from tracker.config.keys import known_keys, resolve_key
from tracker.config.metadata import project as metadata
from tracker.config.defaults import SECTION_TITLES, defaults
from tracker.config.settings import Settings, parse_setting_value

from tracker.core.labels import apply_labels, automatic_label
from tracker.core.identity import apply_moves, identity_of, vanished
from tracker.core.discovery import find_projects, is_project, touched_at

from tracker.ui.ansi import C
from tracker.ui.ask import confirm as ask
from tracker.ui.details import print_details
from tracker.ui.help import print_help, print_topic
from tracker.core.storage import data_path, save_data
from tracker.util.text import parse_time, relative_time
from tracker.core.models import Projects, get_id, new_project

from tracker.ui.render import (
	format_project,
	note_display,
	print_projects,
	render_rows,
	short_times,
	status_colour,
)

from tracker.core.selection import (
	ALL_SELECTORS,
	parse_filter,
	pin_projects,
	resolve_selection,
	select_projects,
	sort_projects,
	status_counts,
	temporary_ids,
)


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
		self.pending = False

		return save_data(self.data, self.settings, undoable=undoable)

	def temporary_ids(self) -> dict[str, int]:
		return temporary_ids(self.data, self.settings)

	def pin(self, projects: Projects) -> dict[str, int]:
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
		selected = select_projects(self.data, self.settings, selectors, quiet=quiet)

		_ = self.mark_used(selected)

		return selected


Handler = Callable[[Context, list[str]], int]


def marks_used(handler: Handler) -> Handler:
	@wraps(handler)
	def wrapper(context: Context, args: list[str]) -> int:
		status = handler(context, args)

		# Looking at a project is not a change worth undoing
		if context.pending and not context.save(undoable=False):
			return 1

		return status

	return wrapper


def missing_project(command: str) -> int:
	print(f"[ERROR] {command} requires a project")
	hint = "a bare #5 is a comment to the shell; please write id:5 or quote it as '#5'"

	print(f"{C.GRAY}        {hint}{C.RESET}")

	return 1


def suggest_command(args: list[str]) -> None:
	from difflib import get_close_matches

	from tracker.cli.app import COMMANDS

	if len(args) != 1:
		return

	matches = get_close_matches(
		args[0].lower().strip("-"), list(COMMANDS), n=1, cutoff=0.7
	)

	if matches:
		print(f"{C.GRAY}        maybe '{COMMANDS[matches[0]]}'?{C.RESET}")


def as_statuses(args: list[str]) -> list[str]:
	return [f"s:{arg}" for arg in args if ":" not in arg and "=" not in arg]


def setting_key(name: str) -> str | None:
	resolved, candidates = resolve_key(name)

	if resolved is not None:
		return resolved

	if candidates:
		print(f"[ERROR] '{name}' could be any of these settings:")

		for candidate in candidates:
			print(f"  {candidate}")

		return None

	print(f"[ERROR] unknown setting '{name}'")

	from difflib import get_close_matches

	close = get_close_matches(name.lower(), known_keys(), n=1, cutoff=0.5)

	if close:
		print(f"{C.GRAY}        maybe '{close[0]}'?{C.RESET}")

	return None


def select_all_or_nothing(
	context: Context, command: str, args: list[str]
) -> Projects | None:
	selected, unmatched = resolve_selection(context.data, context.settings, args)

	if unmatched:
		# Do not repeat a second error
		if len(args) > 1:
			print(f"[ERROR] {command} did nothing, unresolved: {', '.join(unmatched)}")
		else:
			print(f"{C.GRAY}        {command} did nothing{C.RESET}")

		return None

	return selected or None


def confirm(context: Context, question: str) -> bool:
	return ask(
		question,
		assume_yes=context.assume_yes,
		required=bool(context.settings["projects"]["confirm_destructive"]),
	)


def plural(count: int, word: str = "project") -> str:
	return f"{count} {word}{'s' if count != 1 else ''}"


def show_rows(
	context: Context,
	projects: Projects,
	prefix: str = "  ",
	numbering: dict[str, int] | None = None,
) -> None:
	for line in render_rows(
		sort_projects(projects, context.settings),
		context.settings,
		numbering if numbering is not None else context.temporary_ids(),
		show_headers=False,
		prefix=prefix,
	):
		print(line)


#
# Information
#


def command_version(context: Context, args: list[str]) -> int:
	del args

	print(f"{metadata.name.capitalize()} v{metadata.version} by {metadata.author}")

	if context.verbose:
		print(f"  settings  {context.settings.path}")
		print(f"  database  {data_path(context.settings)}")
		print(f"  python    {sys.version.split()[0]}")

	return 0


def command_help(context: Context, args: list[str]) -> int:
	del context

	if args:
		return print_topic(metadata, " ".join(args))

	print_help(metadata)

	return 0


#
# Listing
#

LIMIT_KEYWORDS = frozenset({"all", "a", "max", "full", "*"})


def command_list(context: Context, args: list[str]) -> int:
	settings = context.settings
	options: dict[str, Any] = {"filters": []}

	index = 0

	while index < len(args):
		token = args[index]
		stripped = token.lstrip("-")

		filtered = parse_filter(token)

		if filtered is not None:
			options["filters"].append(filtered)
			index += 1
			continue

		if "=" in stripped and not stripped.startswith(("+", "-")):
			name, _, raw = stripped.partition("=")

			key = setting_key(name)

			if key is None:
				return 1

			try:
				settings = settings.override(key, parse_setting_value(raw))
				context.log(f"override {key} = {raw}")

			except KeyError:
				print(f"[ERROR] unknown setting '{key}'")
				return 1

			except ValueError as error:
				print(f"[ERROR] {error}")
				return 1

			index += 1
			continue

		if token.isdigit():
			settings = settings.override("display.list_limit", int(token))
			index += 1
			continue

		if stripped.lower() in LIMIT_KEYWORDS:
			settings = settings.override("display.list_limit", 0)
			settings = settings.override("display.filter", [])
			index += 1
			continue

		if token.lower() in ("regex", "re"):
			if index + 1 >= len(args):
				print("[ERROR] regex requires a pattern")
				return 1

			options["regex"] = args[index + 1]
			index += 2
			continue

		options["search"] = token
		index += 1

	context.log(f"listing from {data_path(settings)}")

	print_projects(context.data, settings, options)

	return 0


@marks_used
def command_check(context: Context, args: list[str]) -> int:
	if not args:
		return missing_project("check")

	selected = context.select(args)

	if not selected:
		return 1

	numbering = context.pin(selected)

	for index, (path, project) in enumerate(selected.items()):
		if index:
			print()

		print_details(
			path,
			project,
			context.settings,
			numbering.get(path, 0),
			verbose=context.verbose,
		)

	return 0


@marks_used
def command_show(context: Context, args: list[str]) -> int:
	if not args:
		print_projects(context.data, context.settings)
		return 0

	if len(args) == 1 and args[0].lower() in ALL_SELECTORS:
		return command_list(context, ["all"])

	selected, unmatched = resolve_selection(
		context.data, context.settings, args, quiet=True
	)

	if not selected:
		# A word that names no project may be a status
		selected = context.select(as_statuses(args), quiet=True)
		unmatched = []

	if not selected:
		_ = context.select(args)

		suggest_command(args)

		return 1

	_ = context.mark_used(selected)

	if unmatched:
		_ = resolve_selection(context.data, context.settings, unmatched)

	numbering = context.pin(selected)

	if len(selected) == 1:
		path, project = next(iter(selected.items()))

		print_details(
			path,
			project,
			context.settings,
			numbering.get(path, 0),
			verbose=context.verbose,
		)

		return 0

	for line in render_rows(
		sort_projects(selected, context.settings),
		context.settings,
		numbering,
		show_headers=False,
	):
		print(line)

	return 0


@marks_used
def command_path(context: Context, args: list[str]) -> int:
	if not args:
		return missing_project("path")

	selected = context.select(args)

	if not selected:
		return 1

	for path in selected:
		print(path)

	return 0


def command_undo(context: Context, args: list[str]) -> int:
	del args

	from tracker.core.undo import differences, restore

	swapped = restore(context.settings)

	if swapped is None:
		print("nothing to undo")

		return 1

	before, after = swapped

	added, removed, changed = differences(before, after)

	print(f"undone, {plural(len(after))} tracked")

	parts = [
		f"{count} {word}"
		for count, word in ((added, "added"), (removed, "removed"), (changed, "changed"))
		if count
	]

	if parts:
		print(f"  {C.GRAY}{', '.join(parts)} back{C.RESET}")

	print(f"  {C.GRAY}undo again to put it back{C.RESET}")

	return 0


def command_stats(context: Context, args: list[str]) -> int:
	del args

	data = context.data

	if not data:
		print("no projects tracked yet")
		return 0

	settings = context.settings
	time_format: str = settings["display"]["time_format"]
	short = short_times(settings)

	statuses = status_counts(data)

	archived = sum(1 for project in data.values() if project.get("archived"))
	missing = sum(1 for path in data if not Path(path).is_dir())

	print(f"{C.BOLD}Tracked projects{C.RESET}")
	print(f"  {'total'.ljust(14)}{len(data)}")

	if archived:
		print(f"  {'archived'.ljust(14)}{archived}")

	if missing:
		print(f"  {'missing'.ljust(14)}{missing}")

	print(f"\n{C.BOLD}By status{C.RESET}")

	for status, count in sorted(statuses.items(), key=lambda item: (-item[1], item[0])):
		painted = C.paint(status.ljust(14), status_colour(status, settings))
		print(f"  {painted}{count}")

	def stamps(field_name: str) -> list[tuple[Any, str]]:
		found = [
			(parse_time(str(project.get(field_name, "")), time_format), path)
			for path, project in data.items()
		]

		return [(moment, path) for moment, path in found if moment is not None]

	def line(label: str, entry: tuple[Any, str]) -> None:
		when = relative_time(entry[0], short=short)

		print(f"  {label.ljust(14)}{Path(entry[1]).name} ({when})")

	dated = stamps("last_touched")

	if dated:
		print(f"\n{C.BOLD}Activity{C.RESET}")

		line("newest", max(dated))
		line("oldest", min(dated))

	used = stamps("last_used")

	if used:
		print(f"\n{C.BOLD}Used with tracker{C.RESET}")

		line("last", max(used))
		print(f"  {'tracked'.ljust(14)}{len(used)} of {len(data)}")

	print(f"\n{C.GRAY}database: {data_path(settings)}{C.RESET}")

	return 0


#
# Changing the database
#


def follow_moves(
	context: Context, appeared: list[str], root: Path | None = None
) -> list[tuple[str, str]]:
	if not context.settings["scan"]["detect_moves"]:
		return []

	gone = [
		path
		for path in context.data
		if path not in appeared
		and vanished(path, context.data[path])
		and (
			root is None
			or Path(path).is_relative_to(root)
			or context.data[path].get("identity")
		)
	]

	moved = apply_moves(context.data, appeared, gone)

	for _, arrival in moved:
		appeared.remove(arrival)

	return moved


@dataclass
class Scan:
	added: list[str] = field(default_factory=list)
	moved: list[tuple[str, str]] = field(default_factory=list)
	refreshed: int = 0


def scan_into(context: Context, root: Path) -> Scan:
	known = set(context.data)

	_ = find_projects(str(root), context.settings, context.data)

	appeared = [path for path in context.data if path not in known]
	moved = follow_moves(context, appeared, root)

	scanned = {
		path: project
		for path, project in context.data.items()
		if Path(path).is_relative_to(root)
	}

	_ = apply_labels(scanned, context.settings)

	return Scan(appeared, moved, len(scanned) - len(appeared) - len(moved))


def report_moves(moved: list[tuple[str, str]]) -> None:
	if not moved:
		return

	print(f"moved {plural(len(moved))}")

	for old, new in moved:
		print(f"  {C.GRAY}{old}{C.RESET} -> {new}")


def command_add(context: Context, args: list[str]) -> int:
	if not args:
		print("[ERROR] add requires a path")
		return 1

	settings = context.settings
	data = context.data

	path = Path(os.path.expanduser(args[0])).resolve()

	if not path.exists():
		print(f"[ERROR] the path does not exist: {path}")
		return 1

	if not path.is_dir():
		print("[ERROR] the path is not a directory")
		return 1

	status = args[1] if len(args) > 1 else ""
	note = " ".join(args[2:]) if len(args) > 2 else ""

	time_format: str = settings["display"]["time_format"]

	if is_project(path, settings["scan"]["detect_git"]):
		project_path = str(path)

		if project_path in data:
			print("[ERROR] this project is already tracked")
			print(
				format_project(
					project_path,
					data[project_path],
					settings,
					context.pin({project_path: data[project_path]}),
				)
			)
			return 1

		project = new_project(
			project_path,
			status=status or settings["projects"]["default_status"],
			last_touched=touched_at(project_path, settings),
			note=note,
			project_id=get_id(data),
			first_seen=time.strftime(time_format),
			identity=identity_of(project_path),
		)

		if not status:
			project["status"] = automatic_label(project, settings) or project["status"]

		data[project_path] = project

		moved = follow_moves(context, [project_path])

		if moved:
			if status:
				data[project_path]["status"] = status

			if note:
				data[project_path]["note"] = note

		if not context.save():
			return 1

		row = format_project(
			project_path,
			data[project_path],
			settings,
			context.pin({project_path: data[project_path]}),
		)

		if moved:
			print(f"moved {row}")
			print(f"  {C.GRAY}{moved[0][0]}{C.RESET} -> {project_path}")
		else:
			print(f"added {row}")

		return 0

	print(f"scanning {path} for projects...")

	scan = scan_into(context, path)

	added, moved = scan.added, scan.moved

	report_moves(moved)

	if not added:
		if not moved:
			print("no new projects found")

		return 0 if not moved or context.save() else 1

	stamp = time.strftime(time_format)

	for project_path in added:
		if status:
			data[project_path]["status"] = status

		if note:
			data[project_path]["note"] = note

		data[project_path]["first_seen"] = stamp

	if not context.save():
		return 1

	print(f"added {plural(len(added))}")

	fresh = {path_: data[path_] for path_ in added}

	show_rows(context, fresh, numbering=context.pin(fresh))

	return 0


def command_init(context: Context, args: list[str]) -> int:
	settings = context.settings

	target = args[0] if args else os.getcwd()
	path = Path(os.path.expanduser(target)).resolve()

	if not path.is_dir():
		print(f"[ERROR] the path does not exist: {path}")
		return 1

	print(f"scanning {path}...")

	started = time.monotonic()

	scan = scan_into(context, path)

	added, moved = scan.added, scan.moved

	context.log(f"scan took {time.monotonic() - started:.2f}s")

	report_moves(moved)

	stamp = time.strftime(settings["display"]["time_format"])

	for project_path in added:
		context.data[project_path]["first_seen"] = stamp

	if context.data and not context.save():
		return 1

	if added:
		print(f"added {plural(len(added))}, {len(context.data)} tracked")
	else:
		print(f"no new projects found ({len(context.data)} tracked)")

	if scan.refreshed > 0:
		print(f"refreshed {scan.refreshed}")

	if added:
		fresh = {path_: context.data[path_] for path_ in added}

		show_rows(context, fresh, numbering=context.pin(fresh))

	return 0


def command_remove(context: Context, args: list[str]) -> int:
	if not args:
		return missing_project("remove")

	settings = context.settings
	data = context.data

	if args[0].lower().strip("-") in ("all", "a", "*"):
		if not data:
			print("no projects to remove")
			return 0

		if not confirm(context, f"remove all {plural(len(data))}?"):
			print("cancelled")
			return 1

		count = len(data)
		data.clear()

		if not context.save():
			return 1

		print(f"removed {count} entries")

		return 0

	selected = select_all_or_nothing(context, "remove", args)

	if selected is None:
		return 1

	if len(selected) > 1 and not confirm(context, f"remove {plural(len(selected))}?"):
		print("cancelled")
		return 1

	lines = render_rows(
		sort_projects(selected, settings),
		settings,
		context.temporary_ids(),
		show_headers=False,
		prefix="  ",
	)

	for project_path in selected:
		del data[project_path]

	if not context.save():
		return 1

	if len(selected) == 1:
		print(f"removed {lines[0].strip()}")
	else:
		print(f"removed {plural(len(selected))}")

		for line in lines:
			print(line)

	return 0


EDIT_FIELDS = ("status", "note")

FIELD_ALIASES = {
	"status": "status",
	"stat": "status",
	"st": "status",
	"s": "status",
	"note": "note",
	"notes": "note",
	"nt": "note",
	"n": "note",
}


@marks_used
def command_edit(context: Context, args: list[str]) -> int:
	if not args:
		return missing_project("edit")

	settings = context.settings

	if len(args) < 2:
		print(f"[ERROR] edit requires a field: {', '.join(EDIT_FIELDS)}")
		return 1

	selected = context.select([args[0]])

	if not selected:
		return 1

	numbering = context.temporary_ids()

	changes: dict[str, tuple[str, str]] = {}
	changed: Projects = {}
	index = 1

	while index < len(args):
		field_name = FIELD_ALIASES.get(args[index].lower().strip("-"), "")

		if not field_name:
			known = ", ".join(EDIT_FIELDS)

			print(f"[ERROR] unknown field '{args[index]}', expected one of: {known}")
			return 1

		if index + 1 >= len(args):
			print(f"[ERROR] edit {field_name} requires a value")
			return 1

		if field_name == "note":
			value = " ".join(args[index + 1 :])
			index = len(args)
		else:
			value = args[index + 1]
			index += 2

		for path, project in selected.items():
			old = str(project.get(field_name, ""))

			if old != value:
				project[field_name] = value
				changed[path] = project

				if len(selected) == 1:
					changes[field_name] = (old, value)

	if len(selected) > 1:
		if not changed:
			print(f"nothing changed, all {plural(len(selected))} already matched")
			return 0

		if not context.save():
			return 1

		untouched = len(selected) - len(changed)
		skipped = f", {untouched} already matched" if untouched else ""

		print(f"edited {plural(len(changed))}{skipped}")

		show_rows(context, changed, numbering=numbering)

		return 0

	if not changes:
		print("nothing changed")
		return 0

	if not context.save():
		return 1

	path, project = next(iter(selected.items()))

	print(f"edited {format_project(path, project, settings, numbering)}")

	empty = '""'

	for field_name, (old, new) in changes.items():
		if field_name == "note":
			was = note_display(old, "GRAY") if old else empty
			now = note_display(new) if new else empty
		else:
			was, now = old or empty, new or empty

		print(f"  {field_name}: {C.GRAY}{was}{C.RESET} -> {now}")

	return 0


def edit_field(context: Context, args: list[str], field_name: str) -> int:
	if not args:
		return missing_project(field_name)

	if len(args) < 2:
		print(f"[ERROR] {field_name} requires a value")
		return 1

	return command_edit(context, [args[0], field_name, " ".join(args[1:])])


def command_note(context: Context, args: list[str]) -> int:
	return edit_field(context, args, "note")


def list_statuses(context: Context) -> int:
	settings = context.settings
	counts = status_counts(context.data)

	if not counts:
		print("no projects tracked yet")
		return 0

	configured = settings.get("display.status_colours", {})
	known = set(configured) if isinstance(configured, dict) else set()

	print(f"{C.BOLD}Statuses in use{C.RESET}")

	for status, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
		print(f"  {C.paint(status.ljust(16), status_colour(status, settings))}{count}")

	unused = sorted(known - set(counts))

	if unused:
		print(f"\n{C.BOLD}Configured but unused{C.RESET}")
		print(f"  {C.GRAY}{', '.join(unused)}{C.RESET}")

	print(f"\n{C.GRAY}t list s:<status>{' ' * 8}only those projects{C.RESET}")
	print(f"{C.GRAY}t list !s:<status>{' ' * 7}everything else{C.RESET}")
	print(
		f"{C.GRAY}t status s:<old> <new>{' ' * 3}move every project from one to another{C.RESET}"
	)

	return 0


def command_status(context: Context, args: list[str]) -> int:
	if not args:
		return list_statuses(context)

	return edit_field(context, args, "status")


def exclusions(settings: Settings) -> list[str]:
	configured = settings.get("scan.exclude", [])

	if not isinstance(configured, list):
		return []

	patterns: list[Any] = configured

	return [str(pattern) for pattern in patterns]


def save_exclusions(patterns: list[str]) -> bool:
	target = paths.editable_settings_file()

	error = write_setting(target, "scan.exclude", patterns)

	if error:
		print(f"[ERROR] {error}")
		return False

	print(f"{C.GRAY}saved to {target}{C.RESET}")

	return True


def _show_exclusions(patterns: list[str]) -> int:
	if not patterns:
		print("nothing is excluded from scans")
		return 0

	print(f"{C.BOLD}Excluded from scans{C.RESET}")

	for pattern in patterns:
		print(f"  {pattern}")

	return 0


def _clear_exclusions(context: Context, patterns: list[str], wanted: list[str]) -> int:
	if not patterns:
		print("nothing is excluded from scans")
		return 0

	if not wanted:
		if not confirm(context, f"stop excluding all {len(patterns)} patterns?"):
			print("cancelled")
			return 1

		return 0 if save_exclusions([]) else 1

	dropped = [pattern for pattern in patterns if pattern in wanted]

	if not dropped:
		print(f"[ERROR] nothing excluded matches '{' '.join(wanted)}'")
		return 1

	kept = [pattern for pattern in patterns if pattern not in dropped]

	if not save_exclusions(kept):
		return 1

	for pattern in dropped:
		print(f"no longer excluded: {pattern}")

	return 0


def command_forget(context: Context, args: list[str]) -> int:
	settings = context.settings
	patterns = exclusions(settings)

	action = args[0].lower().strip("-") if args else "list"

	if action in ("list", "l", "show"):
		return _show_exclusions(patterns)

	if action in ("clear", "c", "reset", "allow"):
		return _clear_exclusions(context, patterns, args[1:])

	selected = select_all_or_nothing(context, "forget", args)

	if selected is None:
		return 1

	if len(selected) > 1 and not confirm(context, f"forget {plural(len(selected))}?"):
		print("cancelled")
		return 1

	lines = render_rows(
		sort_projects(selected, settings),
		settings,
		context.temporary_ids(),
		show_headers=False,
		prefix="  ",
	)

	for project_path in selected:
		del context.data[project_path]

	if not context.save():
		return 1

	updated = list(patterns)

	for project_path in selected:
		if project_path not in updated:
			updated.append(project_path)

	if not save_exclusions(updated):
		return 1

	print(f"forgot {plural(len(selected))}")

	for line in lines:
		print(line)

	return 0


SHELLS = ("bash", "zsh", "fish")


def _completion_words(context: Context, prefix: str) -> None:
	from tracker.cli.app import COMMANDS

	candidates = set(COMMANDS)

	for path in context.data:
		candidates.add(Path(path).name)

	for status in status_counts(context.data):
		candidates.add(status)
		candidates.add(f"s:{status}")
		candidates.add(f"!s:{status}")

	for key in known_keys():
		candidates.add(key)
		candidates.add(key.split(".")[-1])

	lowered = prefix.lower()

	for candidate in sorted(candidates):
		if candidate.lower().startswith(lowered):
			print(candidate)


def command_completion(context: Context, args: list[str]) -> int:
	action = args[0].lower().strip("-") if args else ""

	if action in ("words", "w"):
		_completion_words(context, args[1] if len(args) > 1 else "")
		return 0

	if action in SHELLS:
		script = paths.bundled_file(f"completion.{action}")

		try:
			print(script.read_text(encoding="utf-8").rstrip())
		except OSError as error:
			print(f"[ERROR] could not read {script}: {error}")
			return 1

		return 0

	if action:
		print(f"[ERROR] unknown shell '{args[0]}'")
	else:
		print("[ERROR] completion needs a shell")

	print(f"available: {', '.join(SHELLS)}")
	print(f'{C.GRAY}  eval "$(tracker completion bash)"{C.RESET}')

	return 1


#
# Settings
#


def _display_settings(context: Context) -> None:
	settings = context.settings
	reference = defaults()

	print(f"{C.BOLD}{C.CYAN}Tracker settings{C.RESET}")
	print(f"{C.GRAY}{'-' * 70}{C.RESET}")
	print(f"{C.GRAY}source: {settings.path}{C.RESET}")

	if settings.path == paths.bundled_file(paths.SETTINGS_NAME):
		notice = f"these are the shipped defaults, `settings edit` copies them to {paths.user_settings_file()}"

		print(f"{C.GRAY}{notice}{C.RESET}")

	def label_of(key: str) -> str:
		return key.replace("_", " ").title()

	width = max((len(label_of(key.split(".")[-1])) for key in known_keys()), default=22)

	for section, title in SECTION_TITLES.items():
		data = settings.raw.get(section)

		if not isinstance(data, dict):
			continue

		print(f"\n{C.BOLD}{title}{C.RESET}")

		section_values: dict[str, Any] = data
		section_defaults: dict[str, Any] = reference.get(section, {})

		for key, value in section_values.items():
			label = label_of(key)

			if isinstance(value, list):
				entries: list[Any] = value
				shown = ", ".join(str(item) for item in entries) or "-"
			elif isinstance(value, dict):
				shown = f"{len(value)} entries"
			else:
				shown = str(value)

			changed = section_defaults.get(key, object()) != value
			marker = f" {C.GRAY}(changed){C.RESET}" if changed else ""

			print(f"  {label:<{width}} {C.YELLOW}{shown}{C.RESET}{marker}")

	for problem in settings.problems:
		print(f"\n{C.YELLOW}[WARNING] {problem}{C.RESET}")


def command_settings(context: Context, args: list[str]) -> int:
	settings = context.settings

	if not args:
		_display_settings(context)
		return 0

	action = args[0].lower().strip("-")

	if action in ("edit", "e"):
		settings.edit()
		return 0

	if action in ("path", "p", "where", "w"):
		print(settings.path)
		return 0

	if action in ("get", "g"):
		if len(args) < 2:
			print("[ERROR] get requires a setting name")
			return 1

		for name in args[1:]:
			key = setting_key(name)

			if key is None:
				return 1

			print(f"{key} = {settings.get(key)}")

		return 0

	if action in ("set", "s"):
		if len(args) < 3:
			print("[ERROR] set requires a setting name and a value")
			return 1

		key = setting_key(args[1])

		if key is None:
			return 1

		raw = " ".join(args[2:])
		target = paths.editable_settings_file()

		try:
			updated = settings.override(key, parse_setting_value(raw))
		except KeyError:
			print(f"[ERROR] unknown setting '{key}'")
			return 1
		except ValueError as error:
			print(f"[ERROR] {error}")
			return 1

		value = updated.get(key)

		error = write_setting(target, key, value)

		if error:
			print(f"[ERROR] {error}")
			return 1

		print(f"{key} = {value}")
		print(f"{C.GRAY}saved to {target}{C.RESET}")

		return 0

	print(f"[ERROR] unknown settings action '{args[0]}'")
	print("available: edit, path, get, set")

	return 1


#
# Daemon
#


def command_daemon(context: Context, args: list[str]) -> int:
	action = args[0].lower().strip("-") if args else "start"

	if action in ("kill", "k", "stop"):
		return daemon.stop(context.settings, assume_yes=context.assume_yes)

	if action in ("status", "st", "state"):
		return daemon.status(context.settings)

	if action in ("log", "logs", "l"):
		lines = 40

		if len(args) > 1 and args[1].isdigit():
			lines = int(args[1])

		return daemon.show_log(lines)

	if action in ("run", "foreground", "fg"):
		return daemon.run(context.settings)

	if action in ("restart", "r"):
		_ = daemon.stop(context.settings, assume_yes=context.assume_yes)
		return daemon.start(context.settings)

	if action in ("start", "s"):
		return daemon.start(context.settings)

	if args:
		print(f"[ERROR] unknown daemon action '{args[0]}'")
		print("available: start, stop, restart, status, log, run")
		return 1

	return daemon.start(context.settings)
