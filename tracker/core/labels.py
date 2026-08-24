from datetime import datetime

from tracker.config.settings import Settings
from tracker.core.models import Project, Projects
from tracker.util.text import days_since, parse_time

Rule = tuple[float, str]


def rules(settings: Settings) -> list[Rule]:
	configured = settings.get("projects.auto_status_rules", {})

	if not isinstance(configured, dict):
		return []

	table: dict[str, object] = configured

	within: list[Rule] = []
	oldest: list[str] = []

	for status, days in table.items():
		name = str(status).strip().lower()

		try:
			age = float(days)  # pyright: ignore[reportArgumentType]
		except (TypeError, ValueError):
			continue

		if age > 0:
			within.append((age, name))
		else:
			oldest.append(name)

	within.sort()

	if oldest:
		within.append((float("inf"), oldest[0]))

	return within


def managed_statuses(settings: Settings) -> set[str]:
	default = str(settings["projects"]["default_status"]).strip().lower()

	return {status for _, status in rules(settings)} | {default, "unknown"}


def label_of(project: Project, settings: Settings, now: datetime | None = None) -> str:
	ordered = rules(settings)

	if not ordered:
		return ""

	moment = parse_time(
		str(project.get("last_touched", "")), settings["display"]["time_format"]
	)

	if moment is None:
		return ordered[-1][1]

	age = days_since(moment, now)

	for limit, status in ordered:
		if age <= limit:
			return status

	return ""


def enabled(settings: Settings) -> bool:
	return bool(settings["projects"]["auto_status"]) and bool(rules(settings))


def automatic_label(
	project: Project, settings: Settings, now: datetime | None = None
) -> str:
	if not enabled(settings):
		return ""

	return label_of(project, settings, now)


def apply_labels(
	projects: Projects, settings: Settings, now: datetime | None = None
) -> list[tuple[str, str, str]]:
	if not enabled(settings):
		return []

	managed = managed_statuses(settings)
	changes: list[tuple[str, str, str]] = []

	for path, project in projects.items():
		if project.get("archived"):
			continue

		current = str(project.get("status", "")).strip().lower()

		if current not in managed:
			continue

		wanted = label_of(project, settings, now)

		if not wanted or wanted == current:
			continue

		project["status"] = wanted
		changes.append((path, current, wanted))

	return changes
