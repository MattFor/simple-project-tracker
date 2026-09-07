import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from tracker.cli.entries import Context, confirm, plural
from tracker.config import paths
from tracker.config.settings import Settings
from tracker.core import portable
from tracker.core.discovery import excluded, is_project
from tracker.core.identity import (
	fingerprint_of,
	identity_of,
	is_local,
	machine_id,
	mark,
	needs_marking,
)
from tracker.core.models import Project, archive
from tracker.core.storage import data_path
from tracker.ui.ansi import C
from tracker.util.text import parse_time

NAMES = ("check", "report", "fix", "apply", "repair")

Reason = Literal["fingerprint", "identity", "name"]

SHOWN = 8


#
# What is wrong
#


@dataclass
class Merge:
	gone: str
	here: str
	reason: Reason


@dataclass
class Move:
	gone: str
	found: str
	reason: Reason


@dataclass
class Report:
	merges: list[Merge] = field(default_factory=list)
	moves: list[Move] = field(default_factory=list)
	unmarked: list[str] = field(default_factory=list)
	stale: list[str] = field(default_factory=list)
	private: list[str] = field(default_factory=list)
	missing_roots: list[str] = field(default_factory=list)
	scanned: bool = False

	@property
	def repairs(self) -> int:
		return len(self.merges) + len(self.moves) + len(self.unmarked)

	@property
	def total(self) -> int:
		return self.repairs + len(self.stale)


#
# Looking around
#


def _alive(path: str) -> bool:
	return Path(path).is_dir()


def _watched(settings: Settings) -> list[Path]:
	wanted: list[str] = list(settings.get("daemon.paths", []) or [])
	wanted.extend(portable.named_roots(settings).values())

	found: list[Path] = []

	for entry in wanted:
		root = paths.resolve(str(entry))

		if root.is_dir() and root not in found:
			found.append(root)

	return found


def _walk(root: Path, settings: Settings) -> list[str]:
	detect_git: bool = settings["scan"]["detect_git"]
	stop_at_project: bool = settings["scan"]["stop_at_project"]
	follow_symlinks: bool = settings["scan"]["follow_symlinks"]

	exclude: list[str] = settings["scan"]["exclude"]
	ignore: list[str] = settings["projects"]["ignore"]

	found: list[str] = []

	for current_root, dirs, _ in os.walk(root, followlinks=follow_symlinks):
		current = Path(current_root)

		dirs[:] = [directory for directory in dirs if directory not in ignore]

		if not is_project(current, detect_git):
			continue

		here = str(current)

		if not excluded(here, exclude):
			found.append(here)

		if stop_at_project and current != root:
			dirs[:] = []

	return found


#
# Matching one entry to another
#


def _marks(path: str, project: Project | None = None) -> dict[str, str]:
	stored = dict(project or {})

	identity = str(stored.get("identity", "") or "")

	return {
		"fingerprint": str(stored.get("fingerprint", "") or "") or fingerprint_of(path),
		"identity": identity if identity and is_local(identity) else identity_of(path),
		"name": Path(path).name.lower(),
	}


def _match(
	gone: list[tuple[str, dict[str, str]]],
	here: list[tuple[str, dict[str, str]]],
	claimed: set[str],
) -> list[tuple[str, str, Reason]]:
	pairs: list[tuple[str, str, Reason]] = []
	settled: set[str] = set()

	reasons: tuple[Reason, ...] = ("fingerprint", "identity", "name")

	for reason in reasons:
		waiting = [entry for entry in gone if entry[0] not in settled]
		free = [entry for entry in here if entry[0] not in claimed]

		for key, marks in waiting:
			value = marks[reason]

			if not value:
				continue

			candidates = [path for path, other in free if other[reason] == value]
			owners = [path for path, other in waiting if other[reason] == value]

			if len(candidates) != 1 or len(owners) != 1:
				continue

			pairs.append((key, candidates[0], reason))

			settled.add(key)
			claimed.add(candidates[0])

	return pairs


def _named_only(marks: dict[str, str]) -> bool:
	return not marks["fingerprint"] and not marks["identity"]


def _demote_names(entries: Iterable[dict[str, str]]) -> None:
	for marks in entries:
		if not _named_only(marks):
			marks["name"] = ""


def examine(context: Context, *, deep: bool = True) -> Report:
	settings = context.settings
	data = context.data

	report = Report()

	living = {path: project for path, project in data.items() if _alive(path)}
	dead = {path: project for path, project in data.items() if path not in living}

	marked = {path: _marks(path, project) for path, project in living.items()}
	buried = {path: _marks(path, project) for path, project in dead.items()}

	_demote_names(marked.values())
	_demote_names(buried.values())

	claimed: set[str] = set()

	for gone, here, reason in _match(list(buried.items()), list(marked.items()), claimed):
		report.merges.append(Merge(gone, here, reason))

	paired = {entry.gone for entry in report.merges}

	left = [entry for entry in buried.items() if entry[0] not in paired]

	if left and deep:
		report.scanned = True

		known = set(data)
		loose: list[tuple[str, dict[str, str]]] = []

		for root in _watched(settings):
			for path in _walk(root, settings):
				if path not in known:
					loose.append((path, _marks(path)))

		_demote_names(marks for _, marks in loose)

		for gone, found, reason in _match(left, loose, set()):
			report.moves.append(Move(gone, found, reason))

	settled = {move.gone for move in report.moves}

	report.stale = sorted(
		path
		for path, project in dead.items()
		if path not in paired
		and path not in settled
		and not project.get("archived", False)
		and not portable.portable(path)
	)

	report.unmarked = sorted(
		path for path, project in living.items() if needs_marking(project)
	)

	if portable.enabled(settings):
		roots = portable.roots(settings)

		report.private = sorted(
			path for path in data if not portable.shareable(path, roots)
		)

	report.missing_roots = sorted(
		str(entry)
		for entry in (settings.get("daemon.paths", []) or [])
		if not paths.resolve(str(entry)).is_dir()
	)

	return report


#
# Putting it right
#


def _extreme(first: Any, second: Any, time_format: str, *, newest: bool) -> str:
	values = [str(value) for value in (first, second) if str(value or "")]

	if not values:
		return ""

	dated = [
		(moment, value)
		for moment, value in ((parse_time(value, time_format), value) for value in values)
		if moment is not None
	]

	if not dated:
		return values[0]

	return (max(dated) if newest else min(dated))[1]


def _earliest(first: Any, second: Any, time_format: str) -> str:
	return _extreme(first, second, time_format, newest=False)


def _latest(first: Any, second: Any, time_format: str) -> str:
	return _extreme(first, second, time_format, newest=True)


def merge(old: Project, new: Project, settings: Settings) -> None:
	time_format: str = settings["display"]["time_format"]
	default: str = settings["projects"]["default_status"]

	new["id"] = min(int(old.get("id", 0) or 0) or int(new["id"]), int(new["id"]))

	previous = str(old.get("status", "") or "")
	current = str(new.get("status", "") or "")

	if previous and previous not in (default, "unknown"):
		new["status"] = previous
	elif not current:
		new["status"] = previous or default

	kept = str(old.get("note", "") or "").strip()
	fresh = str(new.get("note", "") or "").strip()

	# Neither note is ours to throw away
	if kept and fresh and kept != fresh:
		new["note"] = f"{kept} | {fresh}"
	else:
		new["note"] = kept or fresh

	first_seen = _earliest(old.get("first_seen"), new.get("first_seen"), time_format)

	if first_seen:
		new["first_seen"] = first_seen

	last_used = _latest(old.get("last_used"), new.get("last_used"), time_format)

	if last_used:
		new["last_used"] = last_used

	new["uses"] = int(old.get("uses", 0) or 0) + int(new.get("uses", 0) or 0)

	new["archived"] = False

	_ = new.pop("archived_note", None)
	_ = new.pop("deleted_at", None)


def repair(context: Context, report: Report, *, stale: bool) -> list[str]:
	settings = context.settings
	data = context.data

	done: list[str] = []
	marked = 0

	for entry in report.merges:
		if entry.gone not in data or entry.here not in data:
			continue

		merge(data.pop(entry.gone), data[entry.here], settings)

		marked += int(mark(entry.here, data[entry.here]))

	if report.merges:
		done.append(f"merged {plural(len(report.merges), 'duplicate')}")

	for move in report.moves:
		if move.gone not in data or move.found in data:
			continue

		project = data.pop(move.gone)

		project["path"] = move.found
		project["archived"] = False

		_ = project.pop("archived_note", None)
		_ = project.pop("deleted_at", None)

		data[move.found] = project

		marked += int(mark(move.found, project))

	if report.moves:
		done.append(f"repointed {plural(len(report.moves))}")

	for path in report.unmarked:
		project = data.get(path)

		if project is not None:
			marked += int(mark(path, project))

	if marked:
		done.append(f"marked {plural(marked)}")

	if stale and report.stale:
		now = time.strftime(str(settings["display"]["time_format"]))

		for path in report.stale:
			project = data.get(path)

			if project is not None and not project.get("archived", False):
				archive(project, now)

		done.append(f"archived {plural(len(report.stale), 'missing project')}")

	return done


#
# Saying it out loud
#


def _short(path: str, roots: portable.Roots) -> str:
	return portable.contract(path, roots)


def _listing(rows: list[str], verbose: bool) -> list[str]:
	if verbose or len(rows) <= SHOWN:
		return rows

	return [*rows[:SHOWN], f"{C.GRAY}... and {len(rows) - SHOWN} more{C.RESET}"]


def _heading(title: str, count: int, explanation: str) -> None:
	print(f"\n{C.BOLD}{title}{C.RESET} {C.GRAY}({count}){C.RESET}")
	print(f"  {C.GRAY}{explanation}{C.RESET}\n")


def describe(context: Context, report: Report) -> None:
	settings = context.settings
	roots = portable.roots(settings)

	data = context.data

	print(f"{C.BOLD}Database{C.RESET}")
	print(f"  {'file'.ljust(12)}{data_path(settings)}")
	print(f"  {'projects'.ljust(12)}{len(data)}")
	print(f"  {'machine'.ljust(12)}{machine_id()}")

	sharing = "on" if portable.enabled(settings) else "off"
	named = ", ".join(f"@{name}" for name in sorted(portable.named_roots(settings)))

	print(f"  {'portable'.ljust(12)}{sharing}")
	print(f"  {'roots'.ljust(12)}{named or f'{C.GRAY}home only{C.RESET}'}")

	if report.merges:
		_heading(
			"Tracked twice",
			len(report.merges),
			"one project under two entries, the older one pointing at a path that is gone",
		)

		rows: list[str] = []

		for entry in report.merges:
			project = data.get(entry.gone, {})
			name = Path(entry.here).name

			was = project.get("id", "-")
			now = data.get(entry.here, {}).get("id", "-")

			moving = f"#{was} -> #{now}, by {entry.reason}"

			rows.append(
				"\n".join(
					(
						f"  {C.YELLOW}{name}{C.RESET} {C.GRAY}{moving}{C.RESET}",
						f"      {C.GRAY}gone{C.RESET}  {_short(entry.gone, roots)}",
						f"      {C.GREEN}here{C.RESET}  {_short(entry.here, roots)}",
					)
				)
			)

		for row in _listing(rows, context.verbose):
			print(row)

	if report.moves:
		_heading(
			"Somewhere else now",
			len(report.moves),
			"the project was found on disk at a path the database does not know",
		)

		rows = []

		for move in report.moves:
			name = Path(move.found).name

			rows.append(
				"\n".join(
					(
						f"  {C.YELLOW}{name}{C.RESET} {C.GRAY}by {move.reason}{C.RESET}",
						f"      {C.GRAY}was{C.RESET}   {_short(move.gone, roots)}",
						f"      {C.GREEN}now{C.RESET}   {_short(move.found, roots)}",
					)
				)
			)

		for row in _listing(rows, context.verbose):
			print(row)

	if report.unmarked:
		_heading(
			"Unmarked",
			len(report.unmarked),
			"no record of which repository this is, or of which machine saw it",
		)

		rows = [f"  {Path(path).name}" for path in report.unmarked]

		for row in _listing(rows, context.verbose):
			print(row)

	if report.stale:
		_heading(
			"Missing",
			len(report.stale),
			"nothing at this path, and nothing on disk that matches it"
			if report.scanned
			else "nothing at this path",
		)

		rows = [
			f"  {Path(path).name}\n      {C.GRAY}{_short(path, roots)}{C.RESET}"
			for path in report.stale
		]

		for row in _listing(rows, context.verbose):
			print(row)

	if report.private:
		_heading(
			"Not shareable",
			len(report.private),
			"outside home and outside every root, so another machine cannot place it",
		)

		rows = [f"  {C.GRAY}{path}{C.RESET}" for path in report.private]

		for row in _listing(rows, context.verbose):
			print(row)

		print(f"\n  {C.GRAY}name the directory in [sync.roots] to share these{C.RESET}")

	if report.missing_roots:
		_heading(
			"Watched but not there",
			len(report.missing_roots),
			"daemon.paths names a directory that does not exist",
		)

		for path in report.missing_roots:
			print(f"  {C.RED}{path}{C.RESET}")


#
# The command
#


def command_doctor(context: Context, args: list[str]) -> int:
	wanted = [argument.strip().lower() for argument in args if argument.strip()]

	unknown = [argument for argument in wanted if argument.lstrip("-") not in NAMES]

	if unknown:
		print(f"[ERROR] doctor does not know '{unknown[0]}'")
		print(f"        try: {', '.join(NAMES)}")

		return 1

	applying = any(
		argument.lstrip("-") in ("fix", "apply", "repair") for argument in wanted
	)

	report = examine(context)

	describe(context, report)

	if not report.total:
		print(f"\n{C.GREEN}nothing to repair{C.RESET}")

		return 0

	if not applying:
		print(f"\n{plural(report.repairs, 'repair')} available")
		print(f"{C.GRAY}run `t fix` to make them{C.RESET}")

		return 0

	print()

	if not confirm(context, f"repair {plural(report.repairs, 'thing')}?"):
		print("nothing was changed")

		return 1

	stale = False

	if report.stale:
		stale = confirm(
			context,
			f"also archive {plural(len(report.stale), 'missing project')}?",
		)

	done = repair(context, report, stale=stale)

	if not done:
		print("nothing was changed")

		return 0

	if not context.save():
		return 1

	print()

	for line in done:
		print(f"  {C.GREEN}{line}{C.RESET}")

	print(f"\n{len(context.data)} tracked, undo with `t undo`")

	return 0


def command_fix(context: Context, args: list[str]) -> int:
	asked = [argument.strip().lower().lstrip("-") for argument in args]

	# `t fix check` still only looks
	if any(argument in ("check", "report") for argument in asked):
		return command_doctor(context, args)

	return command_doctor(context, ["fix", *args])
