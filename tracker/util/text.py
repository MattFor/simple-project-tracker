import re
from datetime import datetime

_ANSI = re.compile(r"\033\[[0-9;]*m")
_WHITESPACE = re.compile(r"\s+")

_SEPARATORS = re.compile(r"([-_.\s]+)")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

_ELLIPSIS = "..."
_RESET = "\033[0m"

_TRIM = "-_. "


def strip_ansi(text: str) -> str:
	return _ANSI.sub("", text)


def visible_length(text: str) -> int:
	return len(strip_ansi(text))


def pad(text: str, width: int, right: bool = False) -> str:
	padding = width - visible_length(text)

	if padding <= 0:
		return text

	return " " * padding + text if right else text + " " * padding


def _cut(text: str, width: int) -> str:
	kept: list[str] = []
	visible = 0
	index = 0

	while index < len(text) and visible < width:
		escape = _ANSI.match(text, index)

		if escape is not None:
			kept.append(escape.group(0))
			index = escape.end()
			continue

		kept.append(text[index])

		visible += 1
		index += 1

	return "".join(kept)


def truncate(text: str, width: int) -> str:
	if width <= 0:
		return ""

	length = visible_length(text)

	if length <= width:
		return text

	if width <= len(_ELLIPSIS):
		shortened = _cut(text, width)
	else:
		shortened = _cut(text, width - len(_ELLIPSIS)) + _ELLIPSIS

	if _ANSI.search(shortened) and not shortened.endswith(_RESET):
		shortened += _RESET

	return shortened


#
# Names
#


def words(name: str) -> list[tuple[str, str]]:
	parts: list[tuple[str, str]] = []
	chunks = _SEPARATORS.split(name)

	for index in range(0, len(chunks), 2):
		separator = chunks[index + 1] if index + 1 < len(chunks) else ""
		pieces = [piece for piece in _CAMEL.split(chunks[index]) if piece]

		if not pieces:
			if separator:
				parts.append(("", separator))

			continue

		parts.extend((piece, "") for piece in pieces[:-1])
		parts.append((pieces[-1], separator))

	return parts


def _budgets(lengths: list[int], budget: int) -> list[int]:
	if budget >= sum(lengths):
		return list(lengths)

	level = 1

	while level < max(lengths, default=1) and (
		sum(min(length, level + 1) for length in lengths) <= budget
	):
		level += 1

	kept = [min(length, level) for length in lengths]
	spare = budget - sum(kept)

	for index, length in enumerate(lengths):
		if spare <= 0:
			break

		extra = min(spare, length - kept[index])

		kept[index] += extra
		spare -= extra

	return kept


def abbreviate(name: str, width: int) -> str:
	if width <= 0 or len(name) <= width:
		return name

	parts = words(name)

	if len(parts) < 2:
		return name[:width]

	separators = sum(len(separator) for _, separator in parts)
	budget = width - separators

	if budget < len(parts):
		return name[:width]

	lengths = [len(word) for word, _ in parts]

	kept = _budgets(lengths, budget)

	return "".join(
		word[:keep] + separator
		for (word, separator), keep in zip(parts, kept, strict=True)
	).rstrip(_TRIM)


def shorten(name: str, width: int, continuator: str = _ELLIPSIS) -> str:
	if width <= 0 or len(name) <= width:
		return name

	room = width - len(continuator)

	if room <= 0:
		return name[:width]

	built = ""

	for word, separator in words(name):
		if len(built) + len(word) > room:
			break

		built += word + separator

	built = built.rstrip(_TRIM) or name[:room]

	return built[:room] + continuator


#
# Blocks
#


def flatten(text: str) -> str:
	return _WHITESPACE.sub(" ", text.replace("\n", " . ")).strip()


def wrap(text: str, width: int) -> list[str]:
	if width <= 0:
		return [text] if text else []

	lines: list[str] = []

	for paragraph in text.splitlines() or [""]:
		pieces = paragraph.split()

		if not pieces:
			lines.append("")
			continue

		current = pieces[0]

		for piece in pieces[1:]:
			if visible_length(current) + 1 + visible_length(piece) <= width:
				current = f"{current} {piece}"
			else:
				lines.append(current)
				current = piece

		lines.append(current)

	return lines


def human_size(size: int) -> str:
	value = float(size)

	for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
		if value < 1024 or unit == "TiB":
			if unit == "B":
				return f"{int(value)} {unit}"

			return f"{value:.1f} {unit}"

		value /= 1024

	return f"{value:.1f} TiB"


#
# Time
#


SHORT_UNITS = {
	"second": "s",
	"minute": "m",
	"hour": "h",
	"day": "d",
	"week": "w",
	"month": "mo",
	"year": "y",
}


def relative_time(
	moment: datetime, now: datetime | None = None, *, short: bool = False
) -> str:
	now = now or datetime.now()

	seconds = (now - moment).total_seconds()
	future = seconds < 0
	seconds = abs(seconds)

	steps = (
		(60.0, "second"),
		(60.0, "minute"),
		(24.0, "hour"),
		(7.0, "day"),
		(4.345, "week"),
		(12.0, "month"),
	)

	value = seconds
	# noinspection unused-local
	unit = "second"

	for size, name in steps:
		if value < size:
			unit = name
			break

		value /= size
		# noinspection unused-local
		unit = name

	else:
		unit = "year"

	amount = int(value)

	if unit == "second" and amount < 45:
		return "now" if short else "just now"

	if short:
		suffix = SHORT_UNITS[unit]

		return f"in {amount}{suffix}" if future else f"{amount}{suffix} ago"

	plural = "" if amount == 1 else "s"

	return f"in {amount} {unit}{plural}" if future else f"{amount} {unit}{plural} ago"


def parse_time(value: str, time_format: str) -> datetime | None:
	if not value or value == "unknown":
		return None

	for candidate in (time_format, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
		try:
			return datetime.strptime(value, candidate)
		except (ValueError, TypeError):
			continue

	return None


def days_since(moment: datetime, now: datetime | None = None) -> float:
	return ((now or datetime.now()) - moment).total_seconds() / 86400.0
