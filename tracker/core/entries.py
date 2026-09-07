import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from tracker.config.settings import Settings

Entry = Mapping[str, Any]

E = TypeVar("E", bound=Mapping[str, Any])

Rows = list[tuple[str, Any]]


@dataclass(frozen=True)
class Space:
	noun: str

	view: Callable[[Settings], tuple[Path, str]]
	sort: Callable[[Any, Settings], Rows]
	texts: Callable[[str, Any], list[str]]
	rows: Callable[[Rows, Settings, dict[str, int]], list[str]]
	extra: Callable[[str, Any], list[str]] | None = None
	visible: Callable[[Any, Settings], Any] | None = None

	locate: Callable[[str], str | None] | None = None
	best: Callable[[Rows, Settings, str], tuple[str, Any] | None] | None = None

	@property
	def plural(self) -> str:
		return f"{self.noun}s"


#
# Reading an entry
#


def haystack(key: str, entry: Entry, space: Space) -> list[str]:
	texts = space.texts(key, entry)

	return texts + space.extra(key, entry) if space.extra else texts


def status_of(entry: Entry) -> str:
	return str(entry.get("status", "") or "unknown").strip().lower()


def status_values(value: str) -> list[str]:
	return [piece.strip().lower() for piece in value.split(",") if piece.strip()]


def status_matches(entry: Entry, wanted: list[str]) -> bool:
	status = status_of(entry)

	return any(status == want or status.startswith(want) for want in wanted)


def status_counts(entries: Mapping[str, Entry]) -> dict[str, int]:
	counts: dict[str, int] = {}

	for entry in entries.values():
		status = status_of(entry)
		counts[status] = counts.get(status, 0) + 1

	return counts


#
# Numbering
#


def current_numbering(
	entries: Mapping[str, E], settings: Settings, space: Space
) -> dict[str, int]:
	shown = space.visible(entries, settings) if space.visible else entries

	return {key: tid for tid, (key, _) in enumerate(space.sort(shown, settings), 1)}


def pin_numbering(keys: list[str], settings: Settings, space: Space) -> dict[str, int]:
	from tracker.core.view import save_view

	numbering = {key: number for number, key in enumerate(keys, 1)}

	_ = save_view(*space.view(settings), numbering)

	return numbering


def pin_entries(
	entries: Mapping[str, E], settings: Settings, space: Space
) -> dict[str, int]:
	return pin_numbering(
		[key for key, _ in space.sort(entries, settings)], settings, space
	)


def temporary_ids(
	entries: Mapping[str, E], settings: Settings, space: Space
) -> dict[str, int]:
	from tracker.core.view import load_view

	stored = load_view(*space.view(settings))

	if stored is None:
		return current_numbering(entries, settings, space)

	# One the last listing never showed has no row to point at
	return {key: number for key, number in stored.items() if key in entries}


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
	entries: Mapping[str, E], filter_type: str, value: str, space: Space, quiet: bool
) -> set[str] | None:
	if filter_type == "m":
		needle = value.lower()

		return {
			key
			for key, entry in entries.items()
			if any(needle in text.lower() for text in haystack(key, entry, space))
		}

	if filter_type == "s":
		wanted = status_values(value)

		return {key for key, entry in entries.items() if status_matches(entry, wanted)}

	try:
		pattern = re.compile(value, re.IGNORECASE)
	except re.error as error:
		if not quiet:
			print(f"[ERROR] invalid regex '{value}': {error}")

		return None

	return {
		key
		for key, entry in entries.items()
		if pattern.search(space.texts(key, entry)[-1])
	}


def filter_entries(
	entries: dict[str, E], filters: list[str], space: Space, *, quiet: bool = False
) -> dict[str, E]:
	if not filters:
		return entries

	filtered: dict[str, E] = dict(entries)

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

		matches = _matching(filtered, filter_type, value, space, quiet)

		if matches is None:
			continue

		if action == "+":
			filtered = {key: e for key, e in filtered.items() if key in matches}
		else:
			filtered = {key: e for key, e in filtered.items() if key not in matches}

	return filtered


def search_entries(entries: dict[str, E], search: str, space: Space) -> dict[str, E]:
	needle = search.lower()

	return {
		key: entry
		for key, entry in entries.items()
		if any(needle in text.lower() for text in haystack(key, entry, space))
	}


def regex_entries(
	entries: dict[str, E], expression: str, space: Space
) -> dict[str, E] | None:
	try:
		pattern = re.compile(expression, re.IGNORECASE)
	except re.error as error:
		print(f"[ERROR] invalid regex: {error}")
		return None

	return {
		key: entry
		for key, entry in entries.items()
		if pattern.search(space.texts(key, entry)[-1])
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

# s:blocked, status:blocked,planned -> everything with that status
_STATUS = re.compile(r"(status|state|st|s)[:=](.+)", re.IGNORECASE)

ALL_SELECTORS = ("all", "*")

PREFER_ID = "prefer_id"
PREFER_TID = "prefer_tid"


def status_filter(token: str) -> str | None:
	match = _STATUS.fullmatch(token.strip())

	return match.group(2) if match else None


def resolve_selection(
	entries: dict[str, E],
	settings: Settings,
	selectors: list[str],
	space: Space,
	*,
	quiet: bool = False,
) -> tuple[dict[str, E], list[str]]:
	from tracker.core.frecency import SOURCES

	numbering = temporary_ids(entries, settings, space)
	by_tid = {tid: key for key, tid in numbering.items()}

	selected: dict[str, E] = {}
	unmatched: list[str] = []

	preference: str = settings["projects"]["conflict_resolution_preference"]

	numbers_mean: str = settings["projects"]["number_preference"]
	fallback = f"prefer_{numbers_mean}" if numbers_mean in ("id", "tid") else "any"

	def report(message: str) -> None:
		if not quiet:
			print(message)

	def show(rows: Rows, renumber: bool = False) -> None:
		shown = (
			pin_numbering([key for key, _ in rows], settings, space)
			if renumber
			else numbering
		)

		for line in space.rows(rows, settings, shown):
			report(line)

	def find_number(number: int, source: str = "any") -> list[tuple[str, E]]:
		by_id = [
			(key, entry) for key, entry in entries.items() if entry.get("id") == number
		]

		key = by_tid.get(number)
		by_temporary = [(key, entries[key])] if key is not None else []

		if source == "id":
			return by_id

		if source == "tid":
			return by_temporary

		both = bool(by_id and by_temporary and by_id[0][0] != by_temporary[0][0])

		if source == PREFER_ID:
			return by_id if both else (by_id or by_temporary)

		if source == PREFER_TID:
			return by_temporary if both else (by_id or by_temporary)

		if both:
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
				kind = {"id": "ID", "tid": "TID"}.get(source, "ID/TID")

				report(f"[ERROR] no {space.noun} matches {kind} '{number}'")

			return False

		if len(found) > 1:
			if explain:
				report(f"[ERROR] '{number}' is both an ID and a TID:")
				show(list(found))
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
			report(f"[ERROR] no {space.plural} in the range '{start}-{end}'")

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
			key: entry for key, entry in entries.items() if status_matches(entry, wanted)
		}

		if not matched:
			report(f"[ERROR] no {space.noun} has the status '{value}'")

			known = sorted(status_counts(entries))

			if known:
				report(f"        known statuses: {', '.join(known)}")

			return False

		selected.update(matched)

		return True

	# noinspection shadowing-names
	def select_named(selector: str, complain: bool = True) -> bool:
		wanted = os.path.expanduser(selector) if space.locate else selector
		identifier = wanted.lower().rstrip("/")

		known = [
			(key, entry, [text.lower().rstrip("/") for text in space.texts(key, entry)])
			for key, entry in entries.items()
		]

		# noinspection calling-non-callable
		resolved = space.locate(selector) if space.locate else None

		if resolved is not None:
			for key, entry, texts in known:
				if texts and texts[0] == resolved.lower():
					selected[key] = entry
					return True

		# The widest identifier settles it first, so a path beats a bare name
		for position in range(max((len(texts) for _, _, texts in known), default=0)):
			# noinspection shadowing-names
			exact = [
				(key, entry)
				for key, entry, texts in known
				if position < len(texts) and texts[position] == identifier
			]

			if len(exact) == 1:
				selected[exact[0][0]] = exact[0][1]
				return True

		matched = [
			(key, entry, texts)
			for key, entry, texts in known
			if any(identifier in text for text in texts)
		]

		found = [(key, entry) for key, entry, _ in matched]

		if not found:
			if complain:
				report(f"[ERROR] {space.noun} '{selector}' was not found")

			return False

		if len(found) == 1:
			selected[found[0][0]] = found[0][1]
			return True

		# noinspection shadowing-names
		prefixed = [
			(key, entry)
			for key, entry, texts in matched
			if texts[-1].startswith(identifier)
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

		if preference in SOURCES and space.best is not None:
			found = prefixed or found

			best = space.best(list(found), settings, preference)

			if best is not None:
				selected[best[0]] = best[1]
				return True

		report(f"[ERROR] multiple {space.plural} match '{selector}':")
		show(list(found), renumber=True)

		rows = ", ".join(f":{number}" for number in range(1, min(len(found), 3) + 1))

		report(f"        pick a row with {rows}, or an ID with i:<id>")

		return False

	# noinspection shadowing-names
	def resolve(selector: str) -> bool:
		if selector.lower() in ALL_SELECTORS:
			selected.update(entries)
			return bool(entries)

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

			report(f"[ERROR] '{selector}' is not a known ID, TID or {space.noun}")

			return False

		return select_named(selector)

	for entry in selectors:
		selector = entry.strip()

		if not selector:
			continue

		if not resolve(selector):
			unmatched.append(selector)

	return selected, unmatched


def select_entries(
	entries: dict[str, E],
	settings: Settings,
	selectors: list[str],
	space: Space,
	*,
	quiet: bool = False,
) -> dict[str, E]:
	selected, _ = resolve_selection(entries, settings, selectors, space, quiet=quiet)

	return selected
