import contextlib
import fcntl
import time
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, TypeVar

from tracker.config import paths
from tracker.config.settings import Settings
from tracker.config.settings import settings as default_settings
from tracker.core.models import TRANSIENT_FIELDS, Projects, normalise
from tracker.core.portable import contract_paths, expand_paths
from tracker.util.files import load_legacy_pkl, read_json, save_json

T = TypeVar("T")


#
# Databases
#


def migrate(path: Path, prepare: Callable[[Any], Any], what: str) -> None:
	"""Moves the pickle a database was kept in before 1.4.1 to JSON, once."""

	if path.suffix != ".json":
		return

	legacy = path.with_suffix(".pkl")

	for suffix in ("", ".undo"):
		old = legacy.with_name(legacy.name + suffix)
		new = path.with_name(path.name + suffix)

		if new.exists() or not old.is_file():
			continue

		data, error = load_legacy_pkl(old)

		if error is None and not save_json(new, prepare(data)):
			error = f"could not write {new}"

		if error is not None:
			print(f"[ERROR] the {what} at {old} was not migrated ({error})")
			continue

		with contextlib.suppress(OSError):
			_ = old.replace(old.with_name(f"{old.name}.migrated"))


def read(path: Path, prepare: Callable[[Any], T], what: str) -> T:
	migrate(path, prepare, what)

	data, error = read_json(path)

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


@contextlib.contextmanager
def locked(*files: Path) -> Generator[None]:
	"""Lets one process at a time load, change and save these databases. Take them in this order."""

	with contextlib.ExitStack() as stack:
		for file in files:
			try:
				lock = stack.enter_context(open(file.with_name(f"{file.name}.lock"), "ab"))
				fcntl.flock(lock, fcntl.LOCK_EX)
			except OSError:
				# Android's shared storage has no flock, and a folder not made yet holds nothing to guard
				continue

		yield


def write(path: Path, data: Any, what: str, *, undoable: bool = False) -> bool:
	if undoable:
		from tracker.core.undo import keep_file

		_ = keep_file(path)

	if not save_json(path, data):
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


def save_data(data: Projects, settings: Settings | None = None, *, undoable: bool = False) -> bool:
	for project in data.values():
		for field in TRANSIENT_FIELDS:
			_ = project.pop(field, None)

	return write(data_path(settings), shared(data, settings), "database", undoable=undoable)
