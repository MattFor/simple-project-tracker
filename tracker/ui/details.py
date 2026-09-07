from datetime import datetime
from pathlib import Path

from tracker.config.settings import Settings
from tracker.core.inspect import detect_manifest, disk_usage, git_info
from tracker.core.models import Project
from tracker.ui import mentions
from tracker.ui.ansi import C, markup
from tracker.ui.render import short_times, status_colour
from tracker.util.text import human_size, parse_time, relative_time, wrap

LABEL_WIDTH = 16


def _field(label: str, value: str, colour: str = "") -> None:
	if not value:
		return

	painted = C.paint(value, colour) if colour else value

	print(f"  {C.GRAY}{label.ljust(LABEL_WIDTH)}{C.RESET}{painted}")


def _section(title: str) -> None:
	print(f"\n{C.BOLD}{title}{C.RESET}")


def _stamp(value: str, settings: Settings) -> str:
	if not value:
		return ""

	if value == "unknown":
		return "unknown"

	moment = parse_time(value, settings["display"]["time_format"])

	if moment is None:
		return value

	relative = relative_time(moment, short=short_times(settings))

	return f"{value}  {C.GRAY}({relative}){C.RESET}"


def print_details(
	path: str,
	project: Project,
	settings: Settings,
	tid: int = 0,
	*,
	verbose: bool = False,
) -> None:
	name = Path(path).name
	status = str(project.get("status", "unknown"))

	exists = Path(path).is_dir()

	print(f"{C.BOLD}{name}{C.RESET} {C.GRAY}#{project.get('id', '-')}{C.RESET}")
	print(f"{C.GRAY}{'-' * min(70, max(20, len(name) + 20))}{C.RESET}")

	_section("Tracking")
	_field("ID", str(project.get("id", "-")))
	_field("TID", str(tid) if tid else "-")
	_field("Status", status, status_colour(status, settings))
	_field("Last touched", _stamp(str(project.get("last_touched", "")), settings))
	_field("Last used", _stamp(str(project.get("last_used", "")), settings))
	_field("Uses", str(project.get("uses", 0) or ""))
	_field("First seen", _stamp(str(project.get("first_seen", "")), settings))

	if project.get("archived"):
		_field("Archived", "yes", "yellow")
		_field("Deleted at", _stamp(str(project.get("deleted_at", "")), settings))

	_section("Location")
	_field("Path", path)
	_field("Exists", "yes" if exists else "no", "green" if exists else "red")

	if exists:
		usage = disk_usage(path, settings["projects"]["ignore"])

		_field("Size", human_size(usage.size))
		_field("Files", f"{usage.files:,}")
		_field("Directories", f"{usage.directories:,}")

		manifest = detect_manifest(path)
		language = manifest.language if manifest else usage.top_language

		if language or manifest:
			_section("Project")
			_field("Language", language)

			if manifest:
				_field("Version", manifest.version or "-")
				_field("Package", manifest.name)
				_field("Manifest", manifest.source)

		info = git_info(path)

		if info is not None:
			_section("Git")
			_field("Branch", info.branch + (" (detached)" if info.detached else ""))
			_field("Remote", info.remote or "none")
			_field("Commits", f"{info.commits:,}" if info.commits else "0")

			if info.commit:
				when = (
					f"  {C.GRAY}({relative_time(info.committed)}){C.RESET}"
					if info.committed
					else ""
				)

				_field("Last commit", f"{info.commit} {info.subject}{when}")

			if info.clean:
				_field("Working tree", "clean", "green")
			else:
				parts: list[str] = []

				if info.staged:
					parts.append(f"{info.staged} staged")

				if info.modified:
					parts.append(f"{info.modified} modified")

				if info.untracked:
					parts.append(f"{info.untracked} untracked")

				_field("Working tree", ", ".join(parts), "yellow")

	todos = mentions.todos_about(path, settings)

	if todos:
		from tracker.core.todos import sort_todos

		_section("Todos")

		for _, todo in sort_todos(todos, settings):
			name = str(todo.get("name", ""))
			status = str(todo.get("status", "unknown"))

			_field(f"#{todo.get('id', '-')}", name, status_colour(status, settings))

	note = str(project.get("note", "") or "")

	if note:
		_section("Note")

		for line in note.splitlines() or [note]:
			for piece in wrap(markup(line, "GRAY"), 70) or [""]:
				print(f"  {C.GRAY}{piece}{C.RESET}")

	archived_note = str(project.get("archived_note", "") or "")

	if archived_note and archived_note != note:
		_section("Note before archiving")

		for piece in wrap(markup(archived_note, "GRAY"), 70):
			print(f"  {C.GRAY}{piece}{C.RESET}")

	if verbose:
		extra = {
			key: value
			for key, value in project.items()
			if key
			not in (
				"id",
				"path",
				"status",
				"note",
				"last_touched",
				"last_used",
				"first_seen",
				"deleted_at",
				"archived",
				"archived_note",
			)
		}

		if extra:
			_section("Stored fields")

			for key, value in extra.items():
				_field(key, str(value))

		_section("Database")
		_field("Checked at", datetime.now().strftime(settings["display"]["time_format"]))
