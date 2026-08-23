from typing import Any
from importlib import metadata as importlib_metadata

from tracker.config import paths
from tracker.util.files import load_toml

NAME = "tracker"
VERSION = "1.0.0"
AUTHOR = "MattFor"


def _distribution() -> str:
	try:
		installed = importlib_metadata.packages_distributions().get(NAME, [])
	except Exception:
		return NAME

	return installed[0] if installed else NAME


def _installed() -> dict[str, str]:
	try:
		distribution = importlib_metadata.metadata(_distribution())
	except importlib_metadata.PackageNotFoundError:
		return {}

	author = distribution.get("Author") or ""

	if not author:
		contact = distribution.get("Author-email") or ""
		author = contact.split("<")[0].strip().strip('"') or AUTHOR

	return {
		"name": distribution.get("Name") or NAME,
		"version": distribution.get("Version") or VERSION,
		"author": author,
	}


def _source_tree() -> dict[str, str]:
	if not paths.in_source_tree():
		return {}

	data: dict[str, Any] = load_toml(paths.PROJECT_ROOT / "pyproject.toml") or {}
	table = data.get("project")

	if not isinstance(table, dict):
		return {}

	authors = table.get("authors")
	author = AUTHOR

	if isinstance(authors, list) and authors:
		first = authors[0]
		author = str(first.get("name", AUTHOR) if isinstance(first, dict) else first)

	return {
		"name": str(table.get("name") or NAME),
		"version": str(table.get("version") or VERSION),
		"author": author,
	}


class Metadata:
	def __init__(self) -> None:
		self._data: dict[str, str] = _source_tree() or _installed()

	@property
	def name(self) -> str:
		return self._data.get("name", NAME)

	@property
	def version(self) -> str:
		return self._data.get("version", VERSION)

	@property
	def author(self) -> str:
		return self._data.get("author", AUTHOR)


project = Metadata()
