import time

from pathlib import Path
from typing import Any, TypeVar
from collections.abc import Callable

from tracker.config import paths
from tracker.util.files import load_pkl, save_pkl
from tracker.core.models import TRANSIENT_FIELDS, Projects, normalise
from tracker.config.settings import Settings, settings as default_settings

T = TypeVar("T")


#
# Databases
#


def read(path: Path, prepare: Callable[[Any], T], what: str) -> T:

	data, error = load_pkl(path)

	if error is not None:
		backup = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")

		print(f"[ERROR] the {what} could not be read ({error})")

		try:
			_ = path.replace(backup)
			print(f"the unreadable file was kept as {backup}")
		except OSError:
			pass

		return prepare(None)

	return prepare(data)


def write(path: Path, data: Any, what: str, *, undoable: bool = False) -> bool:
	if undoable:
		from tracker.core.undo import keep_file

		_ = keep_file(path)

	if not save_pkl(path, data):
		print(f"[ERROR] could not write the {what} at {path}")
		return False

	return True


#
# The projects
#


def data_path(settings: Settings | None = None) -> Path:
	settings = settings or default_settings

	return paths.data_file(settings.get("database.file"))


def load_data(settings: Settings | None = None) -> Projects:
	return read(data_path(settings), normalise, "database")


def save_data(
	data: Projects, settings: Settings | None = None, *, undoable: bool = False
) -> bool:
	for project in data.values():
		for field in TRANSIENT_FIELDS:
			_ = project.pop(field, None)

	return write(data_path(settings), data, "database", undoable=undoable)
