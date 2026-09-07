import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tracker.config.defaults import SORT_KEYS
from tracker.config.settings import Settings
from tracker.core import entries as shared
from tracker.core.entries import (
	ALL_SELECTORS,
	FILTER_TYPES,
	Rows,
	Space,
	filter_entries,
	parse_filter,
	regex_entries,
	search_entries,
	status_counts,
	status_matches,
	status_of,
	status_values,
)
from tracker.core.frecency import best_match
from tracker.core.models import Project, Projects
from tracker.util.text import parse_time

__all__ = [
	"ALL_SELECTORS",
	"FILTER_TYPES",
	"PROJECTS",
	"current_numbering",
	"filter_projects",
	"parse_filter",
	"pin_numbering",
	"pin_projects",
	"regex_projects",
	"resolve_selection",
	"search_projects",
	"select_projects",
	"sort_projects",
	"status_counts",
	"status_matches",
	"status_of",
	"status_values",
	"temporary_ids",
	"visible_projects",
]


#
# Sorting
#


def _status_rank(settings: Settings) -> Callable[[str], tuple[int, str]]:
	configured = settings.get("sorting.status_order", [])

	order = (
		[str(entry).strip().lower() for entry in configured]
		if isinstance(configured, list)
		else []
	)

	def rank(status: str) -> tuple[int, str]:
		if not order:
			return 0, status

		return (order.index(status) if status in order else len(order)), status

	return rank


def _sort_key(settings: Settings) -> Callable[[tuple[str, Project]], tuple[Any, str]]:
	sort_by: str = settings["sorting"]["by"]
	time_format: str = settings["display"]["time_format"]

	if sort_by not in SORT_KEYS:
		sort_by = "name"

	rank = _status_rank(settings)

	def key(item: tuple[str, Project]) -> tuple[Any, str]:
		path, project = item

		name = Path(path).name.lower()

		if sort_by == "id":
			return project.get("id", 0), name

		if sort_by == "path":
			return path.lower(), name

		if sort_by == "status":
			return rank(status_of(project)), name

		if sort_by in ("last_touched", "time"):
			moment = parse_time(project.get("last_touched", ""), time_format)

			return (moment.timestamp() if moment else float("-inf")), name

		if sort_by in ("last_used", "used"):
			moment = parse_time(project.get("last_used", ""), time_format)

			return (moment.timestamp() if moment else float("-inf")), name

		return name, name

	return key


def sort_projects(projects: Projects, settings: Settings) -> list[tuple[str, Project]]:
	reverse = settings["sorting"]["direction"] == "descending"

	return sorted(projects.items(), key=_sort_key(settings), reverse=reverse)


#
# The space
#


def _view(settings: Settings) -> tuple[Path, str]:
	from tracker.config import paths
	from tracker.core.storage import data_path

	return paths.view_file(), str(data_path(settings))


def _texts(path: str, project: Project) -> list[str]:
	del project

	return [path, Path(path).name]


def _on_disk(selector: str) -> str | None:
	candidate = Path(os.path.expanduser(selector))

	try:
		if not candidate.is_dir():
			return None

		return str(candidate.resolve())
	except OSError:
		return None


def _rows(rows: Rows, settings: Settings, numbering: dict[str, int]) -> list[str]:
	from tracker.ui.render import render_rows

	view = settings

	try:
		view = view.override("display.format", "")
		view = view.override(
			"display.columns", ["id", "tid", "name", "status", "last_touched"]
		)
	except (KeyError, ValueError):
		view = settings

	return render_rows(rows, view, numbering, show_headers=True, prefix="  ")


#
# Filtering
#


def filter_projects(
	projects: Projects, filters: list[str], *, quiet: bool = False
) -> Projects:
	return filter_entries(projects, filters, PROJECTS, quiet=quiet)


def visible_projects(projects: Projects, settings: Settings) -> Projects:
	configured = settings.get("display.filter", [])

	if not isinstance(configured, list):
		return projects

	filters: list[Any] = configured

	return filter_projects(projects, [str(entry) for entry in filters], quiet=True)


def search_projects(projects: Projects, search: str) -> Projects:
	return search_entries(projects, search, PROJECTS)


def regex_projects(projects: Projects, expression: str) -> Projects | None:
	return regex_entries(projects, expression, PROJECTS)


PROJECTS = Space(
	noun="project",
	view=_view,
	sort=sort_projects,
	texts=_texts,
	rows=_rows,
	visible=visible_projects,
	locate=_on_disk,
	best=best_match,
)


#
# Numbering
#


def current_numbering(projects: Projects, settings: Settings) -> dict[str, int]:
	return shared.current_numbering(projects, settings, PROJECTS)


def pin_numbering(paths: list[str], settings: Settings) -> dict[str, int]:
	return shared.pin_numbering(paths, settings, PROJECTS)


def pin_projects(projects: Projects, settings: Settings) -> dict[str, int]:
	return shared.pin_entries(projects, settings, PROJECTS)


def temporary_ids(projects: Projects, settings: Settings) -> dict[str, int]:
	return shared.temporary_ids(projects, settings, PROJECTS)


#
# Selecting
#


def resolve_selection(
	projects: Projects,
	settings: Settings,
	selectors: list[str],
	*,
	quiet: bool = False,
) -> tuple[Projects, list[str]]:
	return shared.resolve_selection(projects, settings, selectors, PROJECTS, quiet=quiet)


def select_projects(
	projects: Projects,
	settings: Settings,
	selectors: list[str],
	*,
	quiet: bool = False,
) -> Projects:
	return shared.select_entries(projects, settings, selectors, PROJECTS, quiet=quiet)
