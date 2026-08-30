import os
import shutil

from pathlib import Path
from dataclasses import dataclass
from collections.abc import Callable

from tracker.ui.ansi import C
from tracker.config import paths
from tracker.ui.help import print_topic
from tracker.cli.entries import Context
from tracker.config.settings import Settings
from tracker.config.writer import write_setting
from tracker.config.metadata import project as metadata


@dataclass(frozen=True)
class Target:
	noun: str
	where: Callable[[Settings], Path]

	# The setting that points at it, empty when the file is the settings itself
	setting: str

	variable: str


def _settings(settings: Settings) -> Path:
	del settings

	return paths.settings_file()


def _database(settings: Settings) -> Path:
	from tracker.core.storage import data_path

	return data_path(settings)


def _todos(settings: Settings) -> Path:
	from tracker.core.todos import todo_path

	return todo_path(settings)


TARGETS = {
	"settings": Target("settings", _settings, "", "TRACKER_SETTINGS"),
	"database": Target("database", _database, "database.file", "TRACKER_DATA"),
	"todos": Target("todo list", _todos, "todos.database", "TRACKER_TODOS"),
}

NAMES = {
	"settings": "settings",
	"setting": "settings",
	"config": "settings",
	"conf": "settings",
	"s": "settings",
	"database": "database",
	"data": "database",
	"db": "database",
	"projects": "database",
	"d": "database",
	"todos": "todos",
	"todo": "todos",
	"td": "todos",
	"t": "todos",
	"list": "todos",
}

SIDECARS = (".undo",)

LABEL_WIDTH = 12


def _shipped(path: Path) -> bool:
	return path == paths.bundled_file(paths.SETTINGS_NAME)


def _show(context: Context) -> int:
	print(f"{C.BOLD}Files{C.RESET}")

	for name, target in TARGETS.items():
		path = target.where(context.settings)
		shown = str(path)

		if path.is_symlink():
			shown = f"{shown} {C.GRAY}->{C.RESET} {path.resolve()}"
		elif not path.exists():
			shown = f"{shown} {C.GRAY}(not written yet){C.RESET}"

		print(f"  {C.GRAY}{name.ljust(LABEL_WIDTH)}{C.RESET}{shown}")

		override = os.environ.get(target.variable)

		if override:
			print(f"  {' ' * LABEL_WIDTH}{C.YELLOW}{target.variable}={override}{C.RESET}")

	print(f"\n{C.GRAY}t move <what> <where>{C.RESET}")

	return 0


def _carry(current: Path, destination: Path) -> list[str]:
	"""The undo copy should be where the database it represents is."""

	carried: list[str] = []

	for suffix in SIDECARS:
		beside = current.with_name(current.name + suffix)

		if not beside.is_file():
			continue

		_ = shutil.move(
			str(beside), str(destination.with_name(destination.name + suffix))
		)

		carried.append(beside.name)

	return carried


def _link(destination: Path) -> bool:
	link = paths.user_settings_file()

	try:
		link.parent.mkdir(parents=True, exist_ok=True)

		if link.is_symlink():
			link.unlink()
		elif link.exists():
			print(f"[ERROR] {link} is a file of its own, move or remove it first")
			return False

		link.symlink_to(destination)

	except OSError as error:
		print(f"[ERROR] could not link {link}: {error}")
		return False

	print(f"{C.GRAY}{link} -> {destination}{C.RESET}")

	return True


def _repoint(context: Context, target: Target, wanted: str, destination: Path) -> int:
	if not target.setting:
		return 0 if _link(destination) else 1

	value = wanted if wanted.startswith("~") else str(destination)

	editable = paths.editable_settings_file()

	error = write_setting(editable, target.setting, value)

	if error:
		print(f"[ERROR] {error}")
		return 1

	del context

	print(f"{C.GRAY}{target.setting} = {value}{C.RESET}")
	print(f"{C.GRAY}saved to {editable}{C.RESET}")

	return 0


def _relocate(context: Context, target: Target, wanted: str) -> int:
	current = target.where(context.settings)
	destination = paths.resolve(wanted)

	if destination.is_dir() or wanted.endswith(("/", os.sep)):
		destination = destination / current.name

	if destination == current:
		print(f"the {target.noun} is already at {destination}")
		return 0

	try:
		destination.parent.mkdir(parents=True, exist_ok=True)
	except OSError as error:
		print(f"[ERROR] could not make {destination.parent}: {error}")
		return 1

	try:
		if destination.exists():
			print(f"a file is already at {destination}, keeping it")

			if current.exists() and not _shipped(current):
				print(f"{C.GRAY}        the one here stays at {current}{C.RESET}")

		elif _shipped(current):
			_ = shutil.copy2(current, destination)

			print(f"copied the shipped settings to {destination}")

		elif current.exists():
			_ = shutil.move(str(current), str(destination))

			carried = _carry(current, destination)

			print(f"moved the {target.noun} to {destination}")

			for name in carried:
				print(f"{C.GRAY}        {name} came along{C.RESET}")

		else:
			print(f"the {target.noun} will be written at {destination}")

	except OSError as error:
		print(f"[ERROR] could not move to {destination}: {error}")
		return 1

	status = _repoint(context, target, wanted, destination)

	override = os.environ.get(target.variable)

	if override:
		print(f"{C.YELLOW}[WARNING] {target.variable} is set and wins over this{C.RESET}")

	return status


def command_move(context: Context, args: list[str]) -> int:
	if args and args[-1].lower().strip("-") in ("help", "h"):
		return print_topic(metadata, "move")

	if not args:
		return _show(context)

	name = NAMES.get(args[0].lower().strip("-"), "")

	if not name:
		print(f"[ERROR] unknown thing to move '{args[0]}'")
		print(f"available: {', '.join(TARGETS)}")

		return 1

	target = TARGETS[name]
	wanted = " ".join(args[1:]).strip()

	if not wanted:
		print(target.where(context.settings))
		return 0

	return _relocate(context, target, wanted)
