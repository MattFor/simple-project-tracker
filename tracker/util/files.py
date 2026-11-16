import contextlib
import json
import os
import pickle
import tomllib
from pathlib import Path
from typing import Any

#
# Writing
#


def atomic_write(path: Path, payload: bytes) -> bool:
	temporary: Path | None = None

	try:
		path.parent.mkdir(parents=True, exist_ok=True)

		temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")

		with open(temporary, "wb") as f:
			_ = f.write(payload)
			f.flush()
			os.fsync(f.fileno())

		os.replace(temporary, path)

		return True

	except OSError:
		if temporary is not None:
			with contextlib.suppress(OSError):
				temporary.unlink(missing_ok=True)

		return False


#
# Json
#


def save_json(path: Path, data: dict[str, Any]) -> bool:
	try:
		payload = json.dumps(data, indent=4).encode("utf-8")
	except (TypeError, ValueError):
		return False

	return atomic_write(path, payload)


def read_json(path: Path) -> tuple[Any, str | None]:
	try:
		with open(path, encoding="utf-8") as f:
			return json.load(f), None

	except FileNotFoundError:
		return None, None

	except (OSError, ValueError, RecursionError) as error:
		return None, f"{type(error).__name__}: {error}"


def load_json(path: Path) -> dict[str, Any] | None:
	data, _ = read_json(path)

	if not isinstance(data, dict):
		return None

	loaded: dict[str, Any] = data

	return loaded


#
# TOML
#


def read_toml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
	try:
		with open(path, "rb") as f:
			return tomllib.load(f), None

	except FileNotFoundError:
		return None, None

	except tomllib.TOMLDecodeError as error:
		return None, f"{path.name} is not valid TOML: {error}"

	except OSError as error:
		return None, f"could not read {path.name}: {error}"


def load_toml(path: Path) -> dict[str, Any] | None:
	data, _ = read_toml(path)
	return data


#
# Pickle, only to migrate the databases written before JSON
#

# Plain data types only, none that can run code as it is rebuilt
SAFE_GLOBALS = frozenset(
	{
		("builtins", "set"),
		("builtins", "frozenset"),
		("datetime", "datetime"),
		("datetime", "date"),
	}
)


class SafeUnpickler(pickle.Unpickler):
	def find_class(self, module: str, name: str) -> Any:
		if (module, name) not in SAFE_GLOBALS:
			raise pickle.UnpicklingError(f"refused {module}.{name}")

		return super().find_class(module, name)


def load_legacy_pkl(path: Path) -> tuple[Any, str | None]:
	try:
		with open(path, "rb") as f:
			return SafeUnpickler(f).load(), None

	except Exception as error:
		return None, f"{type(error).__name__}: {error}"
