from typing import Any
from collections.abc import Iterator

from tracker.config.defaults import OPEN_TABLES, defaults

Tier = tuple[int, int]


def _names(data: dict[str, Any], prefix: str = "") -> Iterator[str]:
	for key, value in data.items():
		path = f"{prefix}.{key}" if prefix else key

		if isinstance(value, dict) and path not in OPEN_TABLES:
			section: dict[str, Any] = value

			yield from _names(section, path)
		else:
			yield path


def known_keys() -> list[str]:
	return list(_names(defaults()))


def _words(name: str) -> list[str]:
	return [piece for piece in name.replace("-", "_").split("_") if piece]


def _initials(name: str) -> str:
	return "".join(word[0] for word in _words(name))


def _match(query: str, name: str) -> int | None:
	if not query:
		return None

	if query == name:
		return 0

	if name.startswith(query):
		return 1

	wanted = _words(query)
	words = _words(name)

	if len(wanted) == len(words) and all(
		word.startswith(piece) for piece, word in zip(wanted, words, strict=True)
	):
		return 2

	if _initials(name) == query:
		return 3

	return None


def _tier(query: str, key: str) -> Tier | None:
	section, _, name = key.partition(".")

	wanted_section, _, wanted_name = query.rpartition(".")

	found = _match(wanted_name, name)

	if found is None:
		return None

	if not wanted_section:
		return found, 0

	owner = _match(wanted_section, section)

	if owner is None:
		return None

	return found, owner


def resolve_key(query: str) -> tuple[str | None, list[str]]:
	"""The full name of a setting, and every candidate when it is ambiguous."""

	query = query.strip().lower()

	if not query:
		return None, []

	if query.count(".") > 1:
		owner, _, _ = query.rpartition(".")

		if owner in known_keys():
			return query, []

		return None, []

	ranked: dict[Tier, list[str]] = {}

	for key in known_keys():
		tier = _tier(query, key)

		if tier is not None:
			ranked.setdefault(tier, []).append(key)

	if not ranked:
		return None, []

	best = ranked[min(ranked)]

	if len(best) == 1:
		return best[0], best

	return None, sorted(best)
