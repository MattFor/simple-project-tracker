from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeVar

from tracker.config.settings import Settings
from tracker.config.settings import settings as default_settings
from tracker.core.models import Projects, normalise
from tracker.core.storage import data_path, load_data, local, save_data, shared
from tracker.util.files import load_pkl, save_pkl

T = TypeVar("T")


def backup_of(path: Path) -> Path:
	return path.with_name(f"{path.name}.undo")


def backup_path(settings: Settings | None = None) -> Path:
	return backup_of(data_path(settings or default_settings))


def keep_file(path: Path) -> bool:
	current, error = load_pkl(path)

	if error is not None:
		return False

	return save_pkl(backup_of(path), current if current is not None else {})


def keep(settings: Settings | None = None) -> bool:
	return keep_file(data_path(settings or default_settings))


def take_back(path: Path, current: Any) -> dict[str, Any] | None:
	backup = backup_of(path)

	if not backup.is_file():
		return None

	kept, error = load_pkl(backup)

	if error is not None or not isinstance(kept, dict):
		return None

	if not save_pkl(backup, current):
		return None

	restored: dict[str, Any] = kept

	return restored


def swap(
	path: Path,
	current: T,
	prepare: Callable[[Any], T],
	save: Callable[[T], bool],
	store: Callable[[T], Any] | None = None,
) -> tuple[T, T] | None:
	kept = take_back(path, store(current) if store else current)

	if kept is None:
		return None

	restored = prepare(kept)

	if not save(restored):
		return None

	return current, restored


def restore(settings: Settings | None = None) -> tuple[Projects, Projects] | None:
	settings = settings or default_settings

	return swap(
		data_path(settings),
		load_data(settings),
		lambda kept: local(normalise(kept), settings),
		lambda data: save_data(data, settings),
		lambda data: shared(data, settings),
	)


def differences(
	before: Mapping[str, Any], after: Mapping[str, Any]
) -> tuple[int, int, int]:
	added = len([key for key in after if key not in before])
	removed = len([key for key in before if key not in after])

	changed = len(
		[key for key, entry in after.items() if key in before and before[key] != entry]
	)

	return added, removed, changed
