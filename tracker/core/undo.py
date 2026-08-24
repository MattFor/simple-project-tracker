from pathlib import Path

from tracker.util.files import load_pkl, save_pkl
from tracker.core.models import Projects, normalise
from tracker.core.storage import data_path, load_data, save_data
from tracker.config.settings import Settings, settings as default_settings


def backup_path(settings: Settings | None = None) -> Path:
	path = data_path(settings or default_settings)

	return path.with_name(f"{path.name}.undo")


def keep(settings: Settings | None = None) -> bool:
	settings = settings or default_settings

	current, error = load_pkl(data_path(settings))

	if error is not None:
		return False

	return save_pkl(backup_path(settings), current if current is not None else {})


def restore(settings: Settings | None = None) -> tuple[Projects, Projects] | None:
	settings = settings or default_settings

	backup = backup_path(settings)

	if not backup.is_file():
		return None

	kept, error = load_pkl(backup)

	if error is not None or not isinstance(kept, dict):
		return None

	current = load_data(settings)
	restored = normalise(kept)

	if not save_pkl(backup, current):
		return None

	if not save_data(restored, settings):
		return None

	return current, restored


def differences(before: Projects, after: Projects) -> tuple[int, int, int]:
	added = len([path for path in after if path not in before])
	removed = len([path for path in before if path not in after])

	changed = len(
		[
			path
			for path, project in after.items()
			if path in before and before[path] != project
		]
	)

	return added, removed, changed
