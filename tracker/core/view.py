from typing import Any

from tracker.config import paths
from tracker.core.storage import data_path
from tracker.util.files import load_json, save_json
from tracker.config.settings import Settings, settings as default_settings

Numbering = dict[str, int]


def _database(settings: Settings) -> str:
	return str(data_path(settings))


def load_numbering(settings: Settings | None = None) -> Numbering | None:
	settings = settings or default_settings

	stored = load_json(paths.view_file())

	if stored is None or stored.get("database") != _database(settings):
		return None

	order: Any = stored.get("order")

	if not isinstance(order, list):
		return None

	paths_in_view: list[Any] = order

	return {
		str(path): number
		for number, path in enumerate(paths_in_view, 1)
		if isinstance(path, str)
	}


def save_numbering(numbering: Numbering, settings: Settings | None = None) -> bool:
	settings = settings or default_settings

	ordered = sorted(numbering.items(), key=lambda item: item[1])

	return save_json(
		paths.view_file(),
		{
			"database": _database(settings),
			"order": [path for path, _ in ordered],
		},
	)
