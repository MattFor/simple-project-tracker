import os
import uuid
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path

from tracker.config import paths
from tracker.core.inspect import git_output
from tracker.core.models import Project, Projects, restore

Key = Callable[[str, Project], str]

MACHINE_NAME = "machine"

GIT_MARK = "git:"
REMOTE_MARK = "remote:"


#
# This machine
#


@lru_cache(maxsize=1)
def machine_id() -> str:
	file = paths.state_dir() / MACHINE_NAME

	try:
		known = file.read_text(encoding="utf-8").strip()
	except OSError:
		known = ""

	if known and ":" not in known:
		return known

	made = uuid.uuid4().hex[:12]

	try:
		file.parent.mkdir(parents=True, exist_ok=True)
		_ = file.write_text(made, encoding="utf-8")
	except OSError:
		pass

	return made


def split_identity(value: str) -> tuple[str, str]:
	pieces = value.split(":")

	if len(pieces) >= 3:
		return pieces[0], ":".join(pieces[1:])

	return "", value


def is_local(value: str) -> bool:
	machine = split_identity(value)[0]

	return not machine or machine == machine_id()


#
# The marks
#


def identity_of(path: str) -> str:
	try:
		stats = (Path(path) / ".git").stat()
	except OSError:
		return ""

	return f"{machine_id()}:{stats.st_dev}:{stats.st_ino}"


@lru_cache(maxsize=512)
def fingerprint_of(path: str) -> str:
	if not os.path.isdir(path):
		return ""

	roots = git_output(path, "rev-list", "--max-parents=0", "HEAD")

	if roots:
		commits = sorted(line.strip() for line in roots.splitlines() if line.strip())

		if commits:
			return f"{GIT_MARK}{commits[0]}"

	remote = git_output(path, "remote", "get-url", "origin")

	if remote:
		return f"{REMOTE_MARK}{remote.strip().rstrip('/').removesuffix('.git').lower()}"

	return ""


def mark(path: str, project: Project) -> bool:
	changed = note_seen(project)

	stored = str(project.get("identity", "") or "")
	machine = split_identity(stored)[0]

	if not machine or machine == machine_id():
		found = identity_of(path)

		if found and found != stored:
			project["identity"] = found
			changed = True

	if not project.get("fingerprint"):
		found = fingerprint_of(path)

		if found:
			project["fingerprint"] = found
			changed = True

	return changed


#
# Which machines have it
#


def _machines(project: Project) -> list[str]:
	recorded = project.get("seen") or []

	return sorted({str(machine) for machine in recorded if machine})


def note_seen(project: Project) -> bool:
	machines = _machines(project)

	if machine_id() in machines:
		return False

	project["seen"] = sorted([*machines, machine_id()])

	return True


def forget_seen(project: Project) -> bool:
	machines = _machines(project)

	if machine_id() not in machines:
		return False

	project["seen"] = [machine for machine in machines if machine != machine_id()]

	return True


def was_seen(project: Project) -> bool:
	machines = _machines(project)

	return not machines or machine_id() in machines


def kept_elsewhere(project: Project) -> bool:
	return bool(_machines(project))


def needs_marking(project: Project) -> bool:
	if not project.get("fingerprint"):
		return True

	stored = str(project.get("identity", "") or "")

	return not stored or not split_identity(stored)[0]


def vanished(path: str, project: Project) -> bool:
	"""The project that lived here is gone, what now?"""
	if not Path(path).is_dir():
		return True

	stored = str(project.get("identity", "") or "")

	if (
		stored
		and is_local(stored)
		and split_identity(identity_of(path))[1] == split_identity(stored)[1]
	):
		return False

	fingerprint = str(project.get("fingerprint", "") or "")

	if fingerprint:
		return fingerprint_of(path) != fingerprint

	return bool(stored) and is_local(stored)


#
# Pairing what left with what arrived
#


def _fingerprint(path: str, project: Project) -> str:
	stored = str(project.get("fingerprint", "") or "")

	return stored or fingerprint_of(path)


def _identity(path: str, project: Project) -> str:
	stored = str(project.get("identity", "") or "")

	if stored and not is_local(stored):
		return ""

	return stored or identity_of(path)


def _name(path: str, project: Project) -> str:
	del project

	return Path(path).name.lower()


def _unmarked_name(path: str, project: Project) -> str:
	if project.get("fingerprint") or project.get("identity"):
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


# Strongest mark first
PAIRINGS: tuple[tuple[Key, Key], ...] = (
	(_fingerprint, _fingerprint),
	(_identity, _identity),
	(_name, _unmarked_name),
)


def detect_moves(
	data: Projects, appeared: Iterable[str], gone: Iterable[str]
) -> dict[str, str]:
	arrived = [path for path in appeared if path in data]
	missing = [path for path in gone if path in data]

	if not arrived or not missing:
		return {}

	moves: dict[str, str] = {}
	taken: set[str] = set()

	for arriving, leaving in PAIRINGS:
		_pair(data, arrived, missing, arriving, leaving, moves, taken)

	return moves


def carry_over(previous: Project, current: Project) -> None:
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

	carried = str(previous.get("fingerprint", "") or "")

	if carried and not current.get("fingerprint"):
		current["fingerprint"] = carried

	# The entry moved
	machines = set(_machines(previous)) | set(_machines(current))

	if machines:
		current["seen"] = sorted(machines)

	current["archived"] = False

	_ = current.pop("archived_note", None)
	_ = current.pop("deleted_at", None)


def apply_moves(
	data: Projects, appeared: Iterable[str], gone: Iterable[str]
) -> list[tuple[str, str]]:
	moves = detect_moves(data, appeared, gone)

	for old, new in moves.items():
		carry_over(data.pop(old), data[new])

	return sorted(moves.items(), key=lambda item: item[1])
