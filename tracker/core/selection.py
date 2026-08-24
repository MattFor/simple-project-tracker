import os
import re

from typing import Any
from pathlib import Path
from collections.abc import Callable, Iterable

from tracker.util.text import parse_time
from tracker.config.settings import Settings
from tracker.config.defaults import SORT_KEYS
from tracker.core.models import Project, Projects
from tracker.core.frecency import SOURCES, best_match


#
# Statuses
#


def status_of(project: Project) -> str:
	return str(project.get("status", "") or "unknown").strip().lower()


def status_values(value: str) -> list[str]:
	return [piece.strip().lower() for piece in value.split(",") if piece.strip()]


def status_matches(project: Project, wanted: Iterable[str]) -> bool:
	status = status_of(project)

	return any(status == want or status.startswith(want) for want in wanted)


def status_counts(projects: Projects) -> dict[str, int]:
	counts: dict[str, int] = {}

	for project in projects.values():
		status = status_of(project)
		counts[status] = counts.get(status, 0) + 1

	return counts


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


def visible_projects(projects: Projects, settings: Settings) -> Projects:
	configured = settings.get("display.filter", [])

	if not isinstance(configured, list):
		return projects

	filters: list[Any] = configured

	return filter_projects(projects, [str(entry) for entry in filters], quiet=True)


def current_numbering(projects: Projects, settings: Settings) -> dict[str, int]:
	ordered = sort_projects(visible_projects(projects, settings), settings)

	return {path: tid for tid, (path, _) in enumerate(ordered, 1)}


def pin_numbering(paths: list[str], settings: Settings) -> dict[str, int]:
	from tracker.core.view import save_numbering

	numbering = {path: number for number, path in enumerate(paths, 1)}

	_ = save_numbering(numbering, settings)

	return numbering


def pin_projects(projects: Projects, settings: Settings) -> dict[str, int]:
	return pin_numbering(
		[path for path, _ in sort_projects(projects, settings)], settings
	)


def temporary_ids(projects: Projects, settings: Settings) -> dict[str, int]:
	from tracker.core.view import load_numbering

	stored = load_numbering(settings)

	if stored is None:
		return current_numbering(projects, settings)

	# A project the last listing never showed has no row to point at
	return {path: number for path, number in stored.items() if path in projects}


#
# Filtering
#

FILTER_TYPES = ("m", "r", "s")

_FILTER_NAMES = {
	"m": "m",
	"match": "m",
	"name": "m",
	"r": "r",
	"re": "r",
	"regex": "r",
	"s": "s",
	"st": "s",
	"state": "s",
	"status": "s",
}

_FILTER = re.compile(
	rf"([+\-!]?)({'|'.join(sorted(_FILTER_NAMES, key=len, reverse=True))})[:=](.+)",
	re.IGNORECASE,
)


def parse_filter(token: str) -> str | None:
	match = _FILTER.fullmatch(token.strip())

	if match is None:
		return None

	sign, kind, value = match.group(1), match.group(2).lower(), match.group(3)

	action = "-" if sign in ("-", "!") else "+"

	return f"{action}{_FILTER_NAMES[kind]}:{value}"


def _matching(
	projects: Projects, filter_type: str, value: str, quiet: bool
) -> set[str] | None:
	if filter_type == "m":
		needle = value.lower()

		return {
			path
			for path in projects
			if needle in Path(path).name.lower() or needle in path.lower()
		}

	if filter_type == "s":
		wanted = status_values(value)

		return {
			path for path, project in projects.items() if status_matches(project, wanted)
		}

	try:
		pattern = re.compile(value, re.IGNORECASE)
	except re.error as error:
		if not quiet:
			print(f"[ERROR] invalid regex '{value}': {error}")

		return None

	return {path for path in projects if pattern.search(Path(path).name)}


def filter_projects(
	projects: Projects, filters: list[str], *, quiet: bool = False
) -> Projects:
	if not filters:
		return projects

	filtered: Projects = dict(projects)

	for entry in filters:
		expression = entry.strip()

		if len(expression) < 4 or expression[2] != ":":
			if expression and not quiet:
				print(f"[ERROR] invalid filter '{expression}', expected +m:value")

			continue

		action = expression[0]
		filter_type = expression[1].lower()
		value = expression[3:]

		if action not in ("+", "-"):
			if not quiet:
				print(f"[ERROR] invalid filter '{expression}', must start with + or -")

			continue

		if filter_type not in FILTER_TYPES:
			if not quiet:
				kinds = ", ".join(FILTER_TYPES)

				print(f"[ERROR] invalid filter '{expression}', type must be {kinds}")

			continue

		if not value:
			continue

		matches = _matching(filtered, filter_type, value, quiet)

		if matches is None:
			continue

		if action == "+":
			filtered = {path: p for path, p in filtered.items() if path in matches}
		else:
			filtered = {path: p for path, p in filtered.items() if path not in matches}

	return filtered


def search_projects(projects: Projects, search: str) -> Projects:
	needle = search.lower()

	return {
		path: project
		for path, project in projects.items()
		if needle in Path(path).name.lower() or needle in path.lower()
	}


def regex_projects(projects: Projects, expression: str) -> Projects | None:
	try:
		pattern = re.compile(expression, re.IGNORECASE)
	except re.error as error:
		print(f"[ERROR] invalid regex: {error}")
		return None

	return {
		path: project
		for path, project in projects.items()
		if pattern.search(Path(path).name)
	}


#
# Selecting
#

# 5 -> a single number | 5+3 -> 5 and the next 3 | 3-7 -> 3 through 7 either way
_NUMERIC = r"\d+(?:[-+]\d+)?"

_RELATIVE = re.compile(r"(\d+)\+(\d+)")
_RANGE = re.compile(r"(\d+)-(\d+)")

# #5 always means the permanent ID | @5 and :5 always mean the temporary ID
_EXPLICIT = re.compile(rf"([#@])({_NUMERIC})")
_SHORT_TID = re.compile(rf":({_NUMERIC})")

_NAMED = re.compile(rf"(tid|id|t|i)[:=]({_NUMERIC})", re.IGNORECASE)

# s:blocked, status:blocked,planned -> every project with that status
_STATUS = re.compile(r"(status|state|st|s)[:=](.+)", re.IGNORECASE)

ALL_SELECTORS = ("all", "*")


def resolve_selection(
	projects: Projects,
	settings: Settings,
	selectors: list[str],
	*,
	quiet: bool = False,
) -> tuple[Projects, list[str]]:
	numbering = temporary_ids(projects, settings)
	by_tid = {tid: path for path, tid in numbering.items()}

	selected: Projects = {}
	unmatched: list[str] = []

	preference: str = settings["projects"]["conflict_resolution_preference"]

	numbers_mean: str = settings["projects"]["number_preference"]
	fallback = numbers_mean if numbers_mean in ("id", "tid") else "any"

	def report(message: str) -> None:
		if not quiet:
			print(message)

	def show(rows: list[tuple[str, Project]], renumber: bool = False) -> None:
		from tracker.ui.render import render_rows

		shown = (
			pin_numbering([path for path, _ in rows], settings) if renumber else numbering
		)

		view = settings

		try:
			view = view.override("display.format", "")
			view = view.override(
				"display.columns", ["id", "tid", "name", "status", "last_touched"]
			)
		except (KeyError, ValueError):
			view = settings

		for line in render_rows(rows, view, shown, show_headers=True, prefix="  "):
			report(line)

	def find_number(number: int, source: str = "any") -> list[tuple[str, Project]]:
		by_id = [
			(path, project)
			for path, project in projects.items()
			if project.get("id") == number
		]

		path = by_tid.get(number)
		by_temporary = [(path, projects[path])] if path is not None else []

		if source == "id":
			return by_id

		if source == "tid":
			return by_temporary

		if by_id and by_temporary and by_id[0][0] != by_temporary[0][0]:
			return by_id + by_temporary

		return by_id or by_temporary

	# True = selected it | False = found nothing | None = it was ambiguous
	def select_number(
		number: int,
		source: str = "any",
		complain: bool = True,
		explain: bool = True,
	) -> bool | None:
		found = find_number(number, source)

		if not found:
			if complain:
				report(f"[ERROR] no project matches ID/TID '{number}'")

			return False

		if len(found) > 1:
			if explain:
				report(f"[ERROR] '{number}' is both an ID and a TID:")
				show(found)
				report(f"        use i:{number} for the ID or t:{number} for the TID")

			return None

		selected[found[0][0]] = found[0][1]

		return True

	def select_range(start: int, end: int, source: str = "any") -> bool | None:
		step = 1 if end >= start else -1

		found = False
		ambiguous: list[int] = []

		for number in range(start, end + step, step):
			if number < 1:
				continue

			outcome = select_number(number, source, complain=False, explain=False)

			if outcome is None:
				ambiguous.append(number)
				continue

			found = outcome or found

		if ambiguous:
			numbers = ", ".join(str(number) for number in ambiguous)
			verb = "are" if len(ambiguous) > 1 else "is"
			span = f"{start}-{end}"

			report(f"[ERROR] {numbers} {verb} both an ID and a TID")
			report(f"        use i:{span} for the IDs or t:{span} for the TIDs")

			return None

		if not found:
			report(f"[ERROR] no projects in the range '{start}-{end}'")

		return found

	def select_numeric(text: str, source: str) -> bool | None:
		relative = _RELATIVE.fullmatch(text)

		if relative:
			start = int(relative.group(1))

			return select_range(start, start + int(relative.group(2)), source)

		span = _RANGE.fullmatch(text)

		if span:
			return select_range(int(span.group(1)), int(span.group(2)), source)

		return select_number(int(text), source)

	def select_status(value: str) -> bool:
		wanted = status_values(value)

		matched = {
			path: project
			for path, project in projects.items()
			if status_matches(project, wanted)
		}

		if not matched:
			report(f"[ERROR] no project has the status '{value}'")

			known = sorted(status_counts(projects))

			if known:
				report(f"        known statuses: {', '.join(known)}")

			return False

		selected.update(matched)

		return True

	def on_disk(selector: str) -> str | None:
		candidate = Path(os.path.expanduser(selector))

		try:
			if not candidate.is_dir():
				return None

			return str(candidate.resolve())
		except OSError:
			return None

	def select_named(selector: str, complain: bool = True) -> bool:
		identifier = os.path.expanduser(selector).lower().rstrip("/")

		resolved = on_disk(selector)

		if resolved is not None:
			for path, project in projects.items():
				if path.lower().rstrip("/") == resolved.lower():
					selected[path] = project
					return True

		exact_path = [
			(path, project)
			for path, project in projects.items()
			if path.lower().rstrip("/") == identifier
		]

		if len(exact_path) == 1:
			selected[exact_path[0][0]] = exact_path[0][1]
			return True

		exact_name = [
			(path, project)
			for path, project in projects.items()
			if Path(path).name.lower() == identifier
		]

		if len(exact_name) == 1:
			selected[exact_name[0][0]] = exact_name[0][1]
			return True

		found = [
			(path, project)
			for path, project in projects.items()
			if identifier in Path(path).name.lower() or identifier in path.lower()
		]

		if not found:
			if complain:
				report(f"[ERROR] project '{selector}' was not found")

			return False

		if len(found) == 1:
			selected[found[0][0]] = found[0][1]
			return True

		prefixed = [
			(path, project)
			for path, project in found
			if Path(path).name.lower().startswith(identifier)
		]

		if preference == "starts_with":
			if len(prefixed) == 1:
				selected[prefixed[0][0]] = prefixed[0][1]
				return True

			if prefixed:
				found = prefixed

		if preference == "first_match":
			ranked = sorted(found, key=lambda item: numbering.get(item[0], 0))

			selected[ranked[0][0]] = ranked[0][1]
			return True

		if preference in SOURCES:
			found = prefixed or found

			best = best_match(found, settings, preference)

			if best is not None:
				selected[best[0]] = best[1]
				return True

		report(f"[ERROR] multiple projects match '{selector}':")
		show(found, renumber=True)

		return False

	def resolve(selector: str) -> bool:
		if selector.lower() in ALL_SELECTORS:
			selected.update(projects)
			return bool(projects)

		explicit = _EXPLICIT.fullmatch(selector)

		if explicit:
			source = "id" if explicit.group(1) == "#" else "tid"

			return select_numeric(explicit.group(2), source) is True

		short = _SHORT_TID.fullmatch(selector)

		if short:
			return select_numeric(short.group(1), "tid") is True

		named = _NAMED.fullmatch(selector)

		if named:
			source = "tid" if named.group(1).lower() in ("t", "tid") else "id"

			return select_numeric(named.group(2), source) is True

		status = _STATUS.fullmatch(selector)

		if status:
			return select_status(status.group(2))

		if _RELATIVE.fullmatch(selector) or _RANGE.fullmatch(selector):
			return select_numeric(selector, fallback) is True

		if selector.isdigit():
			outcome = select_number(int(selector), fallback, complain=False)

			# Ambiguity has already been explained
			if outcome is None:
				return False

			if outcome:
				return True

			if select_named(selector, complain=False):
				return True

			report(f"[ERROR] '{selector}' is not a known ID, TID or project")

			return False

		return select_named(selector)

	for entry in selectors:
		selector = entry.strip()

		if not selector:
			continue

		if not resolve(selector):
			unmatched.append(selector)

	return selected, unmatched


def select_projects(
	projects: Projects,
	settings: Settings,
	selectors: list[str],
	*,
	quiet: bool = False,
) -> Projects:
	selected, _ = resolve_selection(projects, settings, selectors, quiet=quiet)

	return selected
