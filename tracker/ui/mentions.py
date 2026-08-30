import re

from pathlib import Path

from tracker.ui.ansi import C
from tracker.core.todos import Todo, Todos
from tracker.core.entries import status_of
from tracker.config.settings import Settings
from tracker.core.models import Project, Projects

# @tracker, @mattfor.com, @(two words)
MENTION = re.compile(r"@(?:\(([^)]{1,80})\)|([\w.+-]{1,80}))")

_held: dict[str, object] = {}


def use(projects: Projects) -> None:
	_held["projects"] = projects
	_ = _held.pop("numbering", None)


def use_todos(todos: Todos) -> None:
	_held["todos"] = todos


def forget() -> None:
	_held.clear()


def _projects(settings: Settings) -> Projects:
	known = _held.get("projects")

	if not isinstance(known, dict):
		from tracker.core.storage import load_data

		known = load_data(settings)
		_held["projects"] = known

	projects: Projects = known

	return projects


def _todos(settings: Settings) -> Todos:
	known = _held.get("todos")

	if not isinstance(known, dict):
		from tracker.core.todos import load_todos

		known = load_todos(settings)
		_held["todos"] = known

	todos: Todos = known

	return todos


def _numbering(settings: Settings) -> dict[str, int]:
	known = _held.get("numbering")

	if not isinstance(known, dict):
		from tracker.core.selection import temporary_ids

		known = temporary_ids(_projects(settings), settings)
		_held["numbering"] = known

	numbering: dict[str, int] = known

	return numbering


def find(projects: Projects, wanted: str) -> tuple[str, Project] | None:
	name = wanted.strip().lower()

	if not name:
		return None

	if name.isdigit():
		number = int(name)

		by_id = [
			(path, project)
			for path, project in projects.items()
			if project.get("id") == number
		]

		return by_id[0] if len(by_id) == 1 else None

	for candidates in (
		[
			(path, project)
			for path, project in projects.items()
			if Path(path).name.lower() == name
		],
		[
			(path, project)
			for path, project in projects.items()
			if Path(path).name.lower().startswith(name)
		],
		[
			(path, project)
			for path, project in projects.items()
			if name in Path(path).name.lower() or name in path.lower()
		],
	):
		if len(candidates) == 1:
			return candidates[0]

	return None


def label(path: str, project: Project, tid: int) -> str:
	return f"{Path(path).name}#{project.get('id', '-')}:{tid or '-'}"


def render(text: str, settings: Settings, base: str = "") -> str:
	"""Every mention that names one project, painted in its status colour."""

	if "@" not in text:
		return text

	from tracker.ui.render import status_colour

	projects = _projects(settings)

	if not projects:
		return text

	def replace(match: re.Match[str]) -> str:
		found = find(projects, match.group(1) or match.group(2) or "")

		if found is None:
			return match.group(0)

		path, project = found

		shown = label(path, project, _numbering(settings).get(path, 0))
		painted = C.paint(shown, status_colour(status_of(project), settings))

		if painted == shown or not base:
			return painted

		# Pick the surrounding colour back up where the mention left off
		return painted + getattr(C, base.strip().upper(), "")

	return MENTION.sub(replace, text)


#
# What points at what
#


def _wording(todo: Todo) -> str:
	return f"{todo.get('name', '')}\n{todo.get('note', '') or ''}"


def points_at(text: str, projects: Projects) -> list[str]:
	paths: list[str] = []

	for match in MENTION.finditer(text):
		found = find(projects, match.group(1) or match.group(2) or "")

		if found is not None and found[0] not in paths:
			paths.append(found[0])

	return paths


def projects_of(todo: Todo, settings: Settings) -> list[tuple[str, Project]]:
	projects = _projects(settings)

	return [(path, projects[path]) for path in points_at(_wording(todo), projects)]


def todos_about(path: str, settings: Settings) -> Todos:

	projects = _projects(settings)

	if not projects:
		return {}

	return {
		key: todo
		for key, todo in _todos(settings).items()
		if path in points_at(_wording(todo), projects)
	}


def label_of(path: str, project: Project, settings: Settings) -> str:
	from tracker.ui.render import status_colour

	shown = label(path, project, _numbering(settings).get(path, 0))

	return C.paint(shown, status_colour(status_of(project), settings))
