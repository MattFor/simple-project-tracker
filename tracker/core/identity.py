from pathlib import Path
from collections.abc import Callable, Iterable

from tracker.core.models import Project, Projects, restore

Key = Callable[[str, Project], str]


def identity_of(path: str) -> str:
	try:
		stats = (Path(path) / ".git").stat()
	except OSError:
		return ""

	return f"{stats.st_dev}:{stats.st_ino}"


def vanished(path: str, project: Project) -> bool:
	"""The project that lived here is gone, what now?"""
	if not Path(path).is_dir():
		return True

	stored = str(project.get("identity", "") or "")

	return bool(stored) and identity_of(path) != stored


def _identity(path: str, project: Project) -> str:
	stored = str(project.get("identity", "") or "")

	return stored or identity_of(path)


def _name(path: str, project: Project) -> str:
	del project

	return Path(path).name.lower()


def _unfingerprinted_name(path: str, project: Project) -> str:
	if project.get("identity"):
		return ""

	return _name(path, project)


def _pair(
	data: Projects,
	appeared: list[str],
	gone: list[str],
	arriving: Key,
	leaving: Key,
	moves: dict[str, str],
	taken: set[str],
) -> None:
	arrivals: dict[str, list[str]] = {}

	for path in appeared:
		if path in taken:
			continue

		value = arriving(path, data[path])

		if value:
			arrivals.setdefault(value, []).append(path)

	for old in gone:
		if old in moves:
			continue

		value = leaving(old, data[old])
		candidates = arrivals.get(value, []) if value else []

		if len(candidates) != 1:
			continue

		owners = [
			path
			for path in gone
			if path not in moves and leaving(path, data[path]) == value
		]

		if len(owners) != 1:
			continue

		moves[old] = candidates[0]
		taken.add(candidates[0])


def detect_moves(
	data: Projects, appeared: Iterable[str], gone: Iterable[str]
) -> dict[str, str]:
	arrived = [path for path in appeared if path in data]
	missing = [path for path in gone if path in data]

	if not arrived or not missing:
		return {}

	moves: dict[str, str] = {}
	taken: set[str] = set()

	for arriving, leaving in ((_identity, _identity), (_name, _unfingerprinted_name)):
		_pair(data, arrived, missing, arriving, leaving, moves, taken)

	return moves


def apply_moves(
	data: Projects, appeared: Iterable[str], gone: Iterable[str]
) -> list[tuple[str, str]]:
	moves = detect_moves(data, appeared, gone)

	for old, new in moves.items():
		previous = data.pop(old)
		current = data[new]

		if previous.get("archived"):
			restore(previous)

		current["id"] = previous["id"]
		current["status"] = previous["status"]
		current["note"] = str(previous.get("note", "") or "")

		for field in ("first_seen", "last_used"):
			value = previous.get(field)

			if value:
				current[field] = str(value)

		uses = previous.get("uses", 0)

		if uses:
			current["uses"] = uses

		current["archived"] = False

		_ = current.pop("archived_note", None)
		_ = current.pop("deleted_at", None)

	return sorted(moves.items(), key=lambda item: item[1])
