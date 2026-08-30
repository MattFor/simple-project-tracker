import os

from pathlib import Path
from fnmatch import fnmatch
from datetime import datetime
from collections.abc import Callable, Iterable

from tracker.config.settings import Settings
from tracker.core.identity import identity_of
from tracker.core.labels import automatic_label

from tracker.core.models import (
	Project,
	Projects,
	UNKNOWN_TIME,
	get_id,
	new_project,
	restore,
)


def matches_any(name: str, patterns: Iterable[str]) -> bool:
	return any(fnmatch(name, pattern) for pattern in patterns if pattern)


def get_last_touched_date(
	path: str | os.PathLike[str],
	ignore: Iterable[str] = (),
	follow_symlinks: bool = False,
	ignore_files: Iterable[str] = (),
) -> datetime | None:
	root = str(path)

	if not os.path.exists(root):
		return None

	skip = set(ignore)
	skip_files = [str(pattern) for pattern in ignore_files if pattern]

	latest: float | None = None

	stack: list[str] = [root]
	seen: set[tuple[int, int]] = set()

	while stack:
		current = stack.pop()

		try:
			entries = list(os.scandir(current))
		except OSError:
			continue

		for entry in entries:
			try:
				if entry.is_dir(follow_symlinks=follow_symlinks):
					if entry.name in skip:
						continue

					if follow_symlinks:
						stats = entry.stat()
						key = (stats.st_dev, stats.st_ino)

						if key in seen:
							continue

						seen.add(key)

					stack.append(entry.path)
					continue

				if skip_files and matches_any(entry.name, skip_files):
					continue

				mtime = entry.stat(follow_symlinks=False).st_mtime

			except OSError:
				continue

			if latest is None or mtime > latest:
				latest = mtime

	if latest is None:
		try:
			latest = os.stat(root).st_mtime
		except OSError:
			return None

	return datetime.fromtimestamp(latest)


def format_last_touched(moment: datetime | None, time_format: str) -> str:
	if moment is None:
		return UNKNOWN_TIME

	try:
		return moment.strftime(time_format)
	except (ValueError, TypeError):
		return moment.strftime("%Y-%m-%d %H:%M:%S")


def is_project(path: Path, detect_git: bool) -> bool:
	if not detect_git:
		return False

	git = path / ".git"

	return git.is_dir() or git.is_file()


def excluded(path: str, patterns: Iterable[str]) -> bool:
	name = Path(path).name

	for pattern in patterns:
		expanded = os.path.expanduser(str(pattern)).rstrip("/")

		if not expanded:
			continue

		if fnmatch(path, expanded) or fnmatch(name, expanded):
			return True

	return False


def timestamp_filters(settings: Settings) -> tuple[list[str], list[str]]:
	if not settings["scan"]["timestamps_skip_ignored"]:
		return [], []

	ignore: list[str] = settings["projects"]["ignore"]
	ignore_files: list[str] = settings["projects"]["ignore_files"]

	return list(ignore), list(ignore_files)


def touched_at(path: str, settings: Settings) -> str:
	ignore, ignore_files = timestamp_filters(settings)

	return format_last_touched(
		get_last_touched_date(
			path,
			ignore,
			settings["scan"]["follow_symlinks"],
			ignore_files,
		),
		settings["display"]["time_format"],
	)


def find_projects(
	path: str | os.PathLike[str],
	settings: Settings,
	projects: Projects | None = None,
	*,
	on_found: Callable[[str, Project], None] | None = None,
) -> Projects:
	if projects is None:
		projects = {}

	root = Path(os.path.expanduser(str(path))).resolve()

	if not root.is_dir():
		return projects

	recursive: bool = settings["scan"]["recursive"]
	detect_git: bool = settings["scan"]["detect_git"]
	stop_at_project: bool = settings["scan"]["stop_at_project"]
	follow_symlinks: bool = settings["scan"]["follow_symlinks"]

	exclude: list[str] = settings["scan"]["exclude"]
	ignore: list[str] = settings["projects"]["ignore"]
	default_status: str = settings["projects"]["default_status"]

	for current_root, dirs, _ in os.walk(root, followlinks=follow_symlinks):
		current = Path(current_root)

		dirs[:] = [directory for directory in dirs if directory not in ignore]

		if not recursive and current != root:
			dirs[:] = []

		if not is_project(current, detect_git):
			continue

		halts = stop_at_project and current != root

		project_path = str(current)

		if excluded(project_path, exclude):
			if halts:
				dirs[:] = []

			continue

		last_touched = touched_at(project_path, settings)
		known = projects.get(project_path)

		if known is not None:
			known["last_touched"] = last_touched

			if not known.get("identity"):
				known["identity"] = identity_of(project_path)

			# Whatever was wrong is gone
			if known.get("archived", False):
				restore(known)

		else:
			project = new_project(
				project_path,
				status=default_status,
				last_touched=last_touched,
				project_id=get_id(projects),
				identity=identity_of(project_path),
			)

			project["status"] = automatic_label(project, settings) or default_status

			projects[project_path] = project

			if on_found is not None:
				on_found(project_path, project)

		if halts:
			dirs[:] = []

	return projects
