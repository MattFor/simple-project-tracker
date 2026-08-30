from typing import Any
from pathlib import Path

from tracker.config import paths
from tracker.core.storage import data_path
from tracker.util.files import load_json, save_json
from tracker.config.settings import Settings, settings as default_settings

Numbering = dict[str, int]


def _database(settings: Settings) -> str:
	return str(data_path(settings))


def load_view(file: Path, database: str) -> Numbering | None:
	stored = load_json(file)

	if stored is None or stored.get("database") != database:
		return None

	order: Any = stored.get("order")

	if not isinstance(order, list):
		return None

	keys_in_view: list[Any] = order

	return {
		str(key): number
		for number, key in enumerate(keys_in_view, 1)
		if isinstance(key, str)
	}


def save_view(file: Path, database: str, numbering: Numbering) -> bool:
	ordered = sorted(numbering.items(), key=lambda item: item[1])

	return save_json(
		file,
		{
			"database": database,
			"order": [key for key, _ in ordered],
		},
	)


def load_numbering(settings: Settings | None = None) -> Numbering | None:
	settings = settings or default_settings

	return load_view(paths.view_file(), _database(settings))


def save_numbering(numbering: Numbering, settings: Settings | None = None) -> bool:
	settings = settings or default_settings

	return save_view(paths.view_file(), _database(settings), numbering)
