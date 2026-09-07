from typing import Any, NotRequired, TypedDict


class Project(TypedDict):
	id: int

	path: str
	status: str
	last_touched: str

	note: NotRequired[str]

	uses: NotRequired[int]
	seen: NotRequired[list[str]]
	identity: NotRequired[str]
	fingerprint: NotRequired[str]
	first_seen: NotRequired[str]
	last_used: NotRequired[str]
	deleted_at: NotRequired[str]

	archived: NotRequired[bool]
	archived_note: NotRequired[str]


Projects = dict[str, Project]

TRANSIENT_FIELDS = ("tid",)

UNKNOWN_TIME = "unknown"

DELETED_MARKER = "[DELETED]"

TEXT_FIELDS = ("path", "status", "last_touched", "note", "identity", "fingerprint")


def get_id(projects: Projects) -> int:
	if not projects:
		return 1

	known = [project["id"] for project in projects.values() if "id" in project]

	if not known:
		return 1

	return max(known) + 1


def new_project(
	path: str,
	*,
	status: str,
	last_touched: str = UNKNOWN_TIME,
	note: str = "",
	project_id: int = 0,
	first_seen: str = "",
	identity: str = "",
	fingerprint: str = "",
) -> Project:
	project: Project = {
		"id": project_id,
		"path": path,
		"status": status,
		"last_touched": last_touched,
		"note": note,
	}

	if identity:
		project["identity"] = identity

	if fingerprint:
		project["fingerprint"] = fingerprint

	if first_seen:
		project["first_seen"] = first_seen

	return project


def set_field(project: Project, field: str, value: str) -> None:
	if field == "status":
		project["status"] = value
	elif field == "note":
		project["note"] = value


def normalise(projects: Any) -> Projects:
	if not isinstance(projects, dict):
		return {}

	cleaned: dict[str, Any] = {}
	used_ids: set[int] = set()

	for path, project in projects.items():
		if not isinstance(path, str) or not isinstance(project, dict):
			continue

		entry: dict[str, Any] = project

		for field in TRANSIENT_FIELDS:
			_ = entry.pop(field, None)

		project_id = entry.get("id")

		if not isinstance(project_id, int) or project_id in used_ids:
			project_id = max(used_ids, default=0) + 1

		used_ids.add(project_id)

		entry["id"] = project_id
		entry["path"] = str(entry.get("path") or path)
		entry["status"] = str(entry.get("status") or "unknown")
		entry["last_touched"] = str(entry.get("last_touched") or UNKNOWN_TIME)
		entry["note"] = str(entry.get("note") or "")

		for mark in ("identity", "fingerprint"):
			if mark in entry:
				entry[mark] = str(entry[mark] or "")

		if "seen" in entry:
			machines: Any = entry["seen"]

			entry["seen"] = (
				sorted({str(machine) for machine in machines if machine})
				if isinstance(machines, (list, tuple, set))
				else []
			)

		if "uses" in entry:
			try:
				entry["uses"] = max(0, int(entry["uses"]))
			except (TypeError, ValueError):
				entry["uses"] = 0

		if "archived" in entry:
			entry["archived"] = bool(entry["archived"])

		cleaned[path] = entry

	return cleaned


def is_archived(project: Project) -> bool:
	return bool(project.get("archived", False))


def archive(project: Project, timestamp: str) -> None:
	original = str(project.get("note", "") or "")

	project["archived"] = True
	project["deleted_at"] = timestamp
	project["archived_note"] = original

	statistics = [
		f"{DELETED_MARKER} ({timestamp})",
		f"ID: {project.get('id', '-')}",
		f"Last touched: {project.get('last_touched', UNKNOWN_TIME)}",
	]

	first_seen = project.get("first_seen")

	if first_seen:
		statistics.append(f"First seen: {first_seen}")

	if original:
		statistics.append(original)

	project["note"] = "\n".join(statistics)


def restore(project: Project) -> None:
	project["archived"] = False
	project["note"] = str(project.get("archived_note", "") or "")

	_ = project.pop("archived_note", None)
	_ = project.pop("deleted_at", None)
