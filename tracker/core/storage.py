import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from tracker.config import paths
from tracker.config.settings import Settings
from tracker.config.settings import settings as default_settings
from tracker.core.models import TRANSIENT_FIELDS, Projects, normalise
from tracker.core.portable import contract_paths, expand_paths
from tracker.util.files import load_pkl, save_pkl

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
	return local(read(data_path(settings), normalise, "database"), settings)


def local(data: Projects, settings: Settings | None = None) -> Projects:
	return expand_paths(data, settings)


def shared(data: Projects, settings: Settings | None = None) -> Projects:
	return contract_paths(data, settings)


def save_data(
	data: Projects, settings: Settings | None = None, *, undoable: bool = False
) -> bool:
	for project in data.values():
		for field in TRANSIENT_FIELDS:
			_ = project.pop(field, None)

	return write(
		data_path(settings), shared(data, settings), "database", undoable=undoable
	)
