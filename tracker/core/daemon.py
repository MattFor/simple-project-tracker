import os
import sys
import copy
import time
import errno
import signal
import subprocess
import contextlib

from typing import Any
from pathlib import Path
from dataclasses import dataclass, field

from tracker.config import paths
from tracker.config.settings import Settings, settings as default_settings
from tracker.core.discovery import excluded, find_projects
from tracker.core.identity import apply_moves
from tracker.core.labels import apply_labels
from tracker.core.models import (
	Projects,
	archive as archive_project,
	get_id,
	restore,
)
from tracker.core.storage import data_path, load_data, save_data
from tracker.ui.ansi import C
from tracker.ui.ask import confirm
from tracker.util.files import load_json, read_toml, save_json


#
# Process control
#


def read_state() -> dict[str, Any] | None:
	pid_file = paths.daemon_pid_file()

	state = load_json(pid_file)

	if state is None:
		try:
			state = {"pid": int(pid_file.read_text(encoding="utf-8").strip())}
		except (OSError, ValueError):
			return None

	pid = state.get("pid")

	if not isinstance(pid, int):
		return None

	if not is_running(pid):
		with contextlib.suppress(OSError):
			pid_file.unlink(missing_ok=True)

		return None

	return state


def read_pid() -> int | None:
	state = read_state()

	if state is None:
		return None

	pid = state.get("pid")

	return pid if isinstance(pid, int) else None


def is_running(pid: int) -> bool:
	try:
		os.kill(pid, 0)
	except ProcessLookupError:
		return False
	except PermissionError:
		return True
	except OSError as error:
		return error.errno != errno.ESRCH

	return True


def write_pid(
	pid: int, settings: Settings, watched: list[str], started: str = ""
) -> None:
	pid_file = paths.daemon_pid_file()

	state = {
		"pid": pid,
		"settings": str(settings.path),
		"database": str(data_path(settings)),
		"watching": watched,
		"started": started or time.strftime("%Y-%m-%d %H:%M:%S"),
	}

	try:
		pid_file.parent.mkdir(parents=True, exist_ok=True)
	except OSError as error:
		print(f"[ERROR] could not write the pid file: {error}")
		return

	if not save_json(pid_file, state):
		print(f"[ERROR] could not write the pid file: {pid_file}")


def find_stray_daemons() -> list[int]:
	try:
		result = subprocess.run(
			[
				"pgrep",
				"-u",
				str(os.getuid()),
				"-f",
				r"python.*-m (tracker daemon run|src\.daemon)",
			],
			capture_output=True,
			text=True,
			check=False,
		)
	except (OSError, subprocess.SubprocessError):
		return []

	if result.returncode != 0:
		return []

	pids: list[int] = []

	for line in result.stdout.splitlines():
		try:
			pid = int(line.strip())
		except ValueError:
			continue

		if pid not in (os.getpid(), os.getppid()):
			pids.append(pid)

	return pids


def start(settings: Settings | None = None) -> int:
	settings = settings or default_settings

	running = read_pid()

	if running is not None:
		print(f"the daemon is already running (pid {running})")
		return 0

	if not settings["daemon"]["paths"]:
		print("[ERROR] no daemon paths configured")
		print("add them under [daemon] in " + str(settings.path))
		return 1

	log_file = paths.daemon_log_file()

	try:
		log_file.parent.mkdir(parents=True, exist_ok=True)
		log = open(log_file, "a", buffering=1, encoding="utf-8")  # noqa: SIM115
	except OSError as error:
		print(f"[ERROR] could not open the log file: {error}")
		return 1

	try:
		with log:
			process = subprocess.Popen(
				[sys.executable, "-u", "-m", "tracker", "daemon", "run"],
				cwd=str(paths.working_dir()),
				stdin=subprocess.DEVNULL,
				stdout=log,
				stderr=subprocess.STDOUT,
				start_new_session=True,
			)
	except OSError as error:
		print(f"[ERROR] could not start the daemon: {error}")
		return 1

	write_pid(process.pid, settings, _watched_paths(settings))

	print(f"daemon started (pid {process.pid})")
	print(f"logging to {log_file}")

	return 0


def _terminate(pids: list[int]) -> int:
	stopped = 0

	for pid in pids:
		try:
			os.kill(pid, signal.SIGTERM)
			stopped += 1
		except ProcessLookupError:
			continue
		except PermissionError:
			print(f"[ERROR] not allowed to stop daemon {pid}")

	return stopped


def stop(settings: Settings | None = None, *, assume_yes: bool = False) -> int:
	settings = settings or default_settings

	state = read_state() or {}
	pid = state.get("pid")

	if isinstance(pid, int):
		database = str(state.get("database", ""))

		if database:
			print(f"{C.GRAY}it watches the database at {database}{C.RESET}")

			if database != str(data_path(settings)):
				mismatch = "that is not the database this command would use"

				print(f"{C.YELLOW}[WARNING] {mismatch}{C.RESET}")

		stopped = _terminate([pid])

		with contextlib.suppress(OSError):
			paths.daemon_pid_file().unlink(missing_ok=True)

		print(f"stopped {stopped} daemon" if stopped else "no daemons running")

		return 0

	# No pid file to go on
	strays = find_stray_daemons()

	if not strays:
		print("no daemons running")
		return 0

	count = f"{len(strays)} other tracker daemon{'s' if len(strays) != 1 else ''}"

	print(f"no daemon of this configuration is running, {count} still running:")

	for stray in strays:
		print(f"  pid {stray}")

	if not confirm(f"stop {count}?", assume_yes=assume_yes):
		print("cancelled")
		return 1

	stopped = _terminate(strays)

	print(f"stopped {stopped} daemon{'s' if stopped != 1 else ''}")

	return 0


def status(settings: Settings | None = None) -> int:
	settings = settings or default_settings

	state = read_state()

	if state is None:
		print("daemon: not running")
	else:
		print(f"daemon: running (pid {state.get('pid')})")

	print(f"log:      {paths.daemon_log_file()}")
	print(f"pid file: {paths.daemon_pid_file()}")
	print(f"interval: {settings['daemon']['interval']}s")

	running = state.get("watching") if state else None
	watched = running if isinstance(running, list) else _watched_paths(settings)

	if state:
		database = str(state.get("database", ""))
		source = str(state.get("settings", ""))
		started = str(state.get("started", ""))

		if started:
			print(f"started:  {started}")

		if source:
			print(f"settings: {source}")

		if database:
			print(f"database: {database}")

			if database != str(data_path(settings)):
				mismatch = (
					"the running daemon uses a different database than this command"
				)

				print(f"{C.YELLOW}[WARNING] {mismatch}{C.RESET}")

	print("watching:" if watched else "watching: nothing configured")

	for path in watched:
		print(f"  {os.path.abspath(os.path.expanduser(str(path)))}")

	return 0


def show_log(lines: int = 40) -> int:
	log_file = paths.daemon_log_file()

	if not log_file.is_file():
		print(f"no log yet at {log_file}")
		return 0

	try:
		content = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
	except OSError as error:
		print(f"[ERROR] could not read the log: {error}")
		return 1

	for line in content[-lines:]:
		print(line)

	return 0


#
# Scanning
#


def scan_watched(
	watched: list[str], settings: Settings | None = None
) -> tuple[list[Path], Projects]:
	settings = settings or default_settings

	valid: list[Path] = []
	found: Projects = {}

	for entry in watched:
		path = Path(os.path.expanduser(entry)).resolve()

		if not path.is_dir():
			print(f"[ERROR] daemon path is not a directory: {path}")
			continue

		valid.append(path)
		found.update(find_projects(str(path), settings))

	return valid, found


@dataclass
class ScanResult:
	changed: bool = False
	added: list[str] = field(default_factory=list)
	removed: list[str] = field(default_factory=list)
	moved: list[tuple[str, str]] = field(default_factory=list)


def _refresh(data: Projects, found: Projects, timestamp: str) -> None:
	for project_path, scanned_project in found.items():
		existing = data.get(project_path)

		if existing is None:
			entry = copy.deepcopy(scanned_project)

			entry["id"] = get_id(data)
			entry["first_seen"] = timestamp
			entry["archived"] = False

			data[project_path] = entry
			continue

		existing["last_touched"] = scanned_project["last_touched"]

		identity = str(scanned_project.get("identity", "") or "")

		if identity:
			existing["identity"] = identity

		if existing.get("archived", False):
			restore(existing)


def _missing(
	data: Projects, valid: list[Path], found: Projects, exclude: list[str]
) -> list[str]:
	return [
		project_path
		for project_path in data
		if project_path not in found
		and not excluded(project_path, exclude)
		and any(Path(project_path).is_relative_to(root) for root in valid)
	]


def merge_scan(
	data: Projects,
	valid: list[Path],
	found: Projects,
	archive: bool,
	settings: Settings | None = None,
) -> ScanResult:
	settings = settings or default_settings

	before = copy.deepcopy(data)
	before_paths = set(data)

	timestamp = time.strftime(settings["daemon"]["timestamp_format"])
	exclude: list[str] = settings["scan"]["exclude"]

	_refresh(data, found, timestamp)

	added = [path for path in data if path not in before_paths]
	gone = _missing(data, valid, found, exclude)

	moved = apply_moves(data, added, gone) if settings["scan"]["detect_moves"] else []

	for old, new in moved:
		added.remove(new)
		gone.remove(old)

	removed: list[str] = []

	for project_path in gone:
		project = data[project_path]

		if not archive:
			removed.append(project_path)
			del data[project_path]
			continue

		if project.get("archived", False):
			continue

		archive_project(project, timestamp)
		removed.append(project_path)

	_ = apply_labels({path: data[path] for path in data if path in found}, settings)

	return ScanResult(data != before, added, removed, moved)


def update_database(
	watched: list[str],
	archive: bool,
	settings: Settings | None = None,
) -> tuple[Projects, ScanResult]:
	settings = settings or default_settings

	valid, found = scan_watched(watched, settings)

	data = load_data(settings)

	result = merge_scan(data, valid, found, archive, settings)

	if result.changed:
		_ = save_data(data, settings)

	return data, result


def _count(entries: list[Any]) -> str:
	return f"{len(entries)} project{'s' if len(entries) != 1 else ''}"


def _report(title: str, entries: list[tuple[str, str, str]], timestamp: str) -> None:
	if not entries:
		return

	marker_width = max(len(marker) for marker, _, _ in entries)
	name_width = max(len(name) for _, name, _ in entries)

	print(f"[{timestamp}] {title}:")

	for marker, name, path in entries:
		print(f"  {marker:<{marker_width}}  {name:<{name_width}}  {path}")


def _stamp(path: Path) -> float:
	try:
		return path.stat().st_mtime
	except OSError:
		return 0.0


def _settings_source(settings: Settings) -> Path:
	source = settings.path

	if source.is_file():
		return source

	relocated = paths.settings_file()

	if relocated != source and relocated.is_file():
		print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] settings moved to {relocated}")

		return relocated

	return source


def reload_settings(settings: Settings, stamp: float) -> tuple[Settings, float]:
	source = _settings_source(settings)
	current = _stamp(source)

	if source == settings.path and current == stamp:
		return settings, stamp

	loaded, error = read_toml(source)

	if error is not None:
		print(f"[WARNING] {error}, keeping the previous settings")
		return settings, current

	if loaded is None:
		return settings, current

	refreshed = Settings.merged(loaded, path=source)

	for problem in refreshed.problems:
		print(f"[WARNING] {problem}")

	print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] settings reloaded")

	return refreshed, current


def _watched_paths(settings: Settings) -> list[str]:
	configured: list[str] = settings["daemon"]["paths"]

	return [os.path.abspath(os.path.expanduser(path)) for path in configured]


def _interval_of(settings: Settings) -> int:
	interval = settings["daemon"]["interval"]

	if not isinstance(interval, int) or interval < 1:
		return 60

	return interval


def run(settings: Settings | None = None) -> int:
	settings = settings or default_settings

	interval = _interval_of(settings)
	watched = _watched_paths(settings)
	timestamp_format: str = settings["daemon"]["timestamp_format"]

	if not watched:
		print("[ERROR] no daemon paths configured")
		print(f"add them under [daemon] in {settings.path}")
		return 1

	stamp = _stamp(settings.path)
	started_at = time.strftime("%Y-%m-%d %H:%M:%S")

	write_pid(os.getpid(), settings, watched, started_at)

	recorded = (str(settings.path), str(data_path(settings)), list(watched))

	stopping = False

	def request_stop(*_: object) -> None:
		nonlocal stopping
		stopping = True

	_ = signal.signal(signal.SIGTERM, request_stop)
	_ = signal.signal(signal.SIGINT, request_stop)

	print(f"[{time.strftime(timestamp_format)}] daemon started (pid {os.getpid()})")
	print("watching:")

	for path in watched:
		print(f"  {path}")

	print(f"scan interval: {interval}s")

	try:
		while not stopping:
			started = time.monotonic()

			settings, stamp = reload_settings(settings, stamp)

			archive: bool = settings["daemon"]["archive"]
			interval = _interval_of(settings)
			watched = _watched_paths(settings)
			timestamp_format = settings["daemon"]["timestamp_format"]

			data, result = update_database(watched, archive, settings)

			current = (str(settings.path), str(data_path(settings)), list(watched))

			if current != recorded:
				write_pid(os.getpid(), settings, watched, started_at)
				recorded = current

			timestamp = time.strftime(timestamp_format)

			_report(
				f"added {_count(result.added)}",
				[(str(data[path]["id"]), Path(path).name, path) for path in result.added],
				timestamp,
			)

			_report(
				f"moved {_count(result.moved)}",
				[
					(str(data[new]["id"]), Path(new).name, f"{old} -> {new}")
					for old, new in result.moved
				],
				timestamp,
			)

			_report(
				f"removed {_count(result.removed)}",
				[("-", Path(path).name, path) for path in result.removed],
				timestamp,
			)

			if not result.added and not result.removed and result.changed:
				print(f"[{timestamp}] database updated")

			elapsed = time.monotonic() - started
			remaining = max(0.0, interval - elapsed)

			while remaining > 0 and not stopping:
				nap = min(1.0, remaining)
				time.sleep(nap)
				remaining -= nap

	except KeyboardInterrupt:
		pass

	finally:
		try:
			if read_pid() == os.getpid():
				paths.daemon_pid_file().unlink(missing_ok=True)
		except OSError:
			pass

	print(f"[{time.strftime(timestamp_format)}] daemon stopped")

	return 0


if __name__ == "__main__":
	sys.exit(run())
