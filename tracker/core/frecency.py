import os
import shutil
import subprocess
from datetime import datetime

from tracker.config.settings import Settings
from tracker.core.models import Project
from tracker.util.text import parse_time

SOURCES = ("zoxide", "frecency")

ZOXIDE_TIMEOUT = 5

HOUR = 3600.0
DAY = 24 * HOUR
WEEK = 7 * DAY

#
# Zoxide database integration
#


# Read once per run
_cache: dict[str, dict[str, float]] = {}


def read_zoxide() -> dict[str, float]:
	if not shutil.which("zoxide"):
		return {}

	try:
		result = subprocess.run(
			["zoxide", "query", "--list", "--score"],
			capture_output=True,
			text=True,
			timeout=ZOXIDE_TIMEOUT,
			check=False,
		)
	except (OSError, subprocess.SubprocessError):
		return {}

	if result.returncode != 0:
		return {}

	scores: dict[str, float] = {}

	for line in result.stdout.splitlines():
		pieces = line.strip().split(maxsplit=1)

		if len(pieces) != 2:
			continue

		try:
			score = float(pieces[0])
		except ValueError:
			continue

		scores[os.path.normpath(pieces[1])] = score

	return scores


def zoxide_scores() -> dict[str, float]:
	if "scores" not in _cache:
		_cache["scores"] = read_zoxide()

	return _cache["scores"]


def decay(age: float) -> float:
	if age < HOUR:
		return 4.0

	if age < DAY:
		return 2.0

	if age < WEEK:
		return 0.5

	return 0.25


def frecency(project: Project, settings: Settings, now: datetime | None = None) -> float:
	rank = project.get("uses", 0)

	if rank < 1:
		return 0.0

	moment = parse_time(
		str(project.get("last_used", "")), settings["display"]["time_format"]
	)

	if moment is None:
		return rank * 0.25

	return rank * decay(((now or datetime.now()) - moment).total_seconds())


def score_of(
	path: str,
	project: Project,
	settings: Settings,
	source: str,
	now: datetime | None = None,
) -> float:
	if source == "zoxide":
		return zoxide_scores().get(os.path.normpath(path), 0.0)

	return frecency(project, settings, now)


def best_match(
	matches: list[tuple[str, Project]],
	settings: Settings,
	source: str,
	now: datetime | None = None,
) -> tuple[str, Project] | None:
	if not matches:
		return None

	sources = ("zoxide", "frecency") if source == "zoxide" else ("frecency",)

	for attempt in sources:
		scored = [
			(score_of(path, project, settings, attempt, now), path, project)
			for path, project in matches
		]

		scored.sort(key=lambda entry: entry[0], reverse=True)

		best = scored[0]

		if best[0] <= 0:
			continue

		if len(scored) > 1 and scored[1][0] == best[0]:
			continue

		return best[1], best[2]

	return None
