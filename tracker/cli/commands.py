import os
import sys
import time

from typing import Any
from pathlib import Path
from dataclasses import dataclass, field

from tracker.core import daemon
from tracker.config import paths
from tracker.config.writer import write_setting
from tracker.config.metadata import project as metadata
from tracker.config.defaults import SECTION_TITLES, defaults
from tracker.config.settings import Settings, parse_setting_value

from tracker.core.discovery import (
	find_projects,
	format_last_touched,
	get_last_touched_date,
	is_project,
)

from tracker.ui.ansi import C
from tracker.ui.details import print_details
from tracker.ui.help import print_help, print_topic
from tracker.core.storage import data_path, save_data
from tracker.util.text import parse_time, relative_time
from tracker.core.models import Projects, get_id, new_project
from tracker.ui.render import (
	format_project,
	print_projects,
	render_rows,
	short_times,
	status_colour,
)

from tracker.core.selection import (
	parse_filter,
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

	def log(self, message: str) -> None:
		if self.verbose:
			print(f"{C.GRAY}[verbose] {message}{C.RESET}")

	def save(self) -> bool:
		return save_data(self.data, self.settings)

	def temporary_ids(self) -> dict[str, int]:
		return temporary_ids(self.data, self.settings)


def mark_used(context: Context, selected: Projects, *, save: bool = True) -> bool:
	if not selected or not context.settings["projects"]["track_usage"]:
		return False

	stamp = time.strftime(context.settings["display"]["time_format"])

	for project in selected.values():
		project["last_used"] = stamp

	return context.save() if save else True


def missing_project(command: str) -> int:
	print(f"[ERROR] {command} requires a project")
	hint = "a bare #5 is a comment to the shell, write id:5 or quote it as '#5'"

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
	if context.assume_yes:
		return True

	if not context.settings["projects"]["confirm_destructive"]:
		return True

	if not sys.stdin.isatty():
		print("[ERROR] refusing to run without confirmation; pass --yes")
		return False

	try:
		answer = input(f"{question} [y/N] ").strip().lower()
	except (EOFError, KeyboardInterrupt):
		print()
		return False

	return answer in ("y", "yes")


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
			key, _, raw = stripped.partition("=")

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


def command_check(context: Context, args: list[str]) -> int:
	if not args:
		return missing_project("check")

	selected = select_projects(context.data, context.settings, args)

	if not selected:
		return 1

	# noinspection shadowing-names
	temporary_ids = context.temporary_ids()

	for index, (path, project) in enumerate(selected.items()):
		if index:
			print()

		print_details(
			path,
			project,
			context.settings,
			temporary_ids.get(path, 0),
			verbose=context.verbose,
		)

	_ = mark_used(context, selected)

	return 0


def command_show(context: Context, args: list[str]) -> int:
	selected = select_projects(context.data, context.settings, args)

	if not selected:
		suggest_command(args)
		return 1

	# noinspection shadowing-names
	temporary_ids = context.temporary_ids()

	for line in render_rows(
		selected.items(), context.settings, temporary_ids, show_headers=False
	):
		print(line)

	_ = mark_used(context, selected)

	return 0


def command_path(context: Context, args: list[str]) -> int:
	if not args:
		return missing_project("path")

	selected = select_projects(context.data, context.settings, args)

	if not selected:
		return 1

	for path in selected:
		print(path)

	_ = mark_used(context, selected)

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

	# noinspection shadowing-names
	def stamps(field_name: str) -> list[tuple[Any, str]]:
		found = [
			(parse_time(str(project.get(field_name, "")), time_format), path)
			for path, project in data.items()
		]

		return [(moment, path) for moment, path in found if moment is not None]

	# noinspection shadowing-names
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

	status = args[1] if len(args) > 1 else settings["projects"]["default_status"]
	note = " ".join(args[2:]) if len(args) > 2 else ""

	time_format: str = settings["display"]["time_format"]
	ignore = (
		settings["projects"]["ignore"]
		if settings["scan"]["timestamps_skip_ignored"]
		else ()
	)

	if is_project(path, settings["scan"]["detect_git"]):
		project_path = str(path)

		if project_path in data:
			print("[ERROR] this project is already tracked")
			print(
				format_project(
					project_path, data[project_path], settings, context.temporary_ids()
				)
			)
			return 1

		data[project_path] = new_project(
			project_path,
			status=status,
			last_touched=format_last_touched(
				get_last_touched_date(project_path, ignore), time_format
			),
			note=note,
			project_id=get_id(data),
			first_seen=time.strftime(time_format),
		)

		if not context.save():
			return 1

		print(
			f"added {format_project(project_path, data[project_path], settings, context.temporary_ids())}"
		)

		return 0

	print(f"scanning {path} for projects...")

	known = set(data)

	_ = find_projects(str(path), settings, data)

	added = [project_path for project_path in data if project_path not in known]

	if not added:
		print("no new projects found")
		return 0

	stamp = time.strftime(time_format)

	for project_path in added:
		data[project_path]["status"] = status
		data[project_path]["note"] = note
		data[project_path]["first_seen"] = stamp

	if not context.save():
		return 1

	print(f"added {len(added)} project{'s' if len(added) != 1 else ''}")

	# noinspection shadowing-names
	temporary_ids = context.temporary_ids()

	for line in render_rows(
		[(project_path, data[project_path]) for project_path in added],
		settings,
		temporary_ids,
		show_headers=False,
		prefix="  ",
	):
		print(line)

	return 0


def command_init(context: Context, args: list[str]) -> int:
	settings = context.settings

	target = args[0] if args else os.getcwd()
	path = Path(os.path.expanduser(target)).resolve()

	if not path.is_dir():
		print(f"[ERROR] the path does not exist: {path}")
		return 1

	print(f"scanning {path}...")

	known = set(context.data)

	started = time.monotonic()

	_ = find_projects(str(path), settings, context.data)

	added = [project_path for project_path in context.data if project_path not in known]
	updated = len(context.data) - len(known) - len(added)

	context.log(f"scan took {time.monotonic() - started:.2f}s")

	if not added:
		print(f"no new projects found ({len(context.data)} tracked)")

		if context.data:
			_ = context.save()

		return 0

	stamp = time.strftime(settings["display"]["time_format"])

	for project_path in added:
		context.data[project_path]["first_seen"] = stamp

	if not context.save():
		return 1

	print(
		f"added {len(added)} project{'s' if len(added) != 1 else ''}, {len(context.data)} tracked"
	)

	if updated:
		print(f"refreshed {updated}")

	# noinspection shadowing-names
	temporary_ids = context.temporary_ids()

	for line in render_rows(
		[(project_path, context.data[project_path]) for project_path in added],
		settings,
		temporary_ids,
		show_headers=False,
		prefix="  ",
	):
		print(line)

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

		if not confirm(context, f"remove all {len(data)} tracked projects?"):
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

	# noinspection shadowing-names
	temporary_ids = context.temporary_ids()

	if len(selected) > 1 and not confirm(context, f"remove {len(selected)} projects?"):
		print("cancelled")
		return 1

	lines = render_rows(
		selected.items(), settings, temporary_ids, show_headers=False, prefix="  "
	)

	for project_path in selected:
		del data[project_path]

	if not context.save():
		return 1

	if len(selected) == 1:
		print(f"removed {lines[0].strip()}")
	else:
		print(f"removed {len(selected)} projects")

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


def command_edit(context: Context, args: list[str]) -> int:
	if not args:
		return missing_project("edit")

	settings = context.settings

	selected = select_projects(context.data, settings, [args[0]])

	if not selected:
		return 1

	used = mark_used(context, selected, save=False)

	changes: dict[str, tuple[str, str]] = {}
	changed: Projects = {}
	index = 1

	while index < len(args):
		field_name = FIELD_ALIASES.get(args[index].lower().strip("-"), "")

		if not field_name:
			print(
				f"[ERROR] unknown field '{args[index]}', expected one of: {', '.join(EDIT_FIELDS)}"
			)
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
			print(f"nothing changed, all {len(selected)} already matched")

			return 1 if used and not context.save() else 0

		if not context.save():
			return 1

		untouched = len(selected) - len(changed)
		skipped = f", {untouched} already matched" if untouched else ""

		print(f"edited {len(changed)} project{'s' if len(changed) != 1 else ''}{skipped}")

		for line in render_rows(
			sort_projects(changed, settings),
			settings,
			context.temporary_ids(),
			show_headers=False,
			prefix="  ",
		):
			print(line)

		return 0

	if not changes:
		print("nothing changed")

		return 1 if used and not context.save() else 0

	if not context.save():
		return 1

	path, project = next(iter(selected.items()))

	print(f"edited {format_project(path, project, settings, context.temporary_ids())}")

	empty = '""'

	for field_name, (old, new) in changes.items():
		print(f"  {field_name}: {C.GRAY}{old or empty}{C.RESET} -> {new or empty}")

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

	if len(selected) > 1 and not confirm(context, f"forget {len(selected)} projects?"):
		print("cancelled")
		return 1

	lines = render_rows(
		selected.items(),
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

	print(f"forgot {len(selected)} project{'s' if len(selected) != 1 else ''}")

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

	for section, title in SECTION_TITLES.items():
		data = settings.raw.get(section)

		if not isinstance(data, dict):
			continue

		print(f"\n{C.BOLD}{title}{C.RESET}")

		section_values: dict[str, Any] = data
		section_defaults: dict[str, Any] = reference.get(section, {})

		for key, value in section_values.items():
			label = key.replace("_", " ").title()

			if isinstance(value, list):
				entries: list[Any] = value
				shown = ", ".join(str(item) for item in entries) or "-"
			elif isinstance(value, dict):
				shown = f"{len(value)} entries"
			else:
				shown = str(value)

			changed = section_defaults.get(key, object()) != value
			marker = f" {C.GRAY}(changed){C.RESET}" if changed else ""

			print(f"  {label:<22} {C.YELLOW}{shown}{C.RESET}{marker}")

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

		for key in args[1:]:
			value = settings.get(key)

			if value is None:
				print(f"[ERROR] unknown setting '{key}'")
				return 1

			print(f"{key} = {value}")

		return 0

	if action in ("set", "s"):
		if len(args) < 3:
			print("[ERROR] set requires a setting name and a value")
			return 1

		key = args[1]
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
		return daemon.stop()

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
		_ = daemon.stop()
		return daemon.start(context.settings)

	if action in ("start", "s"):
		return daemon.start(context.settings)

	if args:
		print(f"[ERROR] unknown daemon action '{args[0]}'")
		print("available: start, stop, restart, status, log, run")
		return 1

	return daemon.start(context.settings)
