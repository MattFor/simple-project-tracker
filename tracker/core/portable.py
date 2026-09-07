import os
from pathlib import Path
from typing import Any

from tracker.config import paths
from tracker.config.settings import Settings
from tracker.config.settings import settings as default_settings
from tracker.core.models import Project, Projects
from tracker.util.files import load_toml

HOME = "~"
PREFIX = "@"

ROOTS_NAME = "roots.toml"

ENVIRONMENT_PREFIX = "TRACKER_ROOT_"

Roots = list[tuple[str, str]]


def roots_file() -> Path:
	override = os.environ.get("TRACKER_ROOTS")

	if override:
		return paths.resolve(override)

	return paths.config_dir() / ROOTS_NAME


def _table(data: dict[str, Any] | None) -> dict[str, str]:
	if not data:
		return {}

	inner = data.get("roots")
	table: dict[str, Any] = inner if isinstance(inner, dict) else data

	named: dict[str, str] = {}

	for name, value in table.items():
		if isinstance(value, str) and value.strip():
			named[str(name).strip().lower()] = value.strip()

	return named


def _environment() -> dict[str, str]:
	named: dict[str, str] = {}

	for key, value in os.environ.items():
		if key.startswith(ENVIRONMENT_PREFIX) and value.strip():
			named[key[len(ENVIRONMENT_PREFIX) :].strip().lower()] = value.strip()

	return named


def named_roots(settings: Settings | None = None) -> dict[str, str]:
	settings = settings or default_settings

	configured = settings.get("sync.roots", {})
	shared = _table(configured if isinstance(configured, dict) else {})

	return {**shared, **_table(load_toml(roots_file())), **_environment()}


def roots(settings: Settings | None = None) -> Roots:
	found: Roots = []

	for name, value in named_roots(settings).items():
		if not name or "/" in name or ":" in name:
			continue

		local = str(paths.resolve(value)).rstrip("/")

		if local:
			found.append((name, local))

	return sorted(found, key=lambda item: len(item[1]), reverse=True)


def enabled(settings: Settings | None = None) -> bool:
	settings = settings or default_settings

	return bool(settings.get("sync.portable_paths", True))


#
# Both directions
#


def _under(path: str, root: str) -> str | None:
	if path == root:
		return ""

	if path.startswith(f"{root}/"):
		return path[len(root) + 1 :]

	return None


def contract(path: str, known: Roots | None = None) -> str:
	if not path or portable(path):
		return path

	local = path.rstrip("/") or path

	for name, root in roots() if known is None else known:
		rest = _under(local, root)

		if rest is not None:
			return f"{PREFIX}{name}/{rest}" if rest else f"{PREFIX}{name}"

	home = str(Path.home()).rstrip("/")
	rest = _under(local, home) if home else None

	if rest is not None:
		return f"{HOME}/{rest}" if rest else HOME

	return path


def expand(stored: str, known: Roots | None = None) -> str:
	if not stored:
		return stored

	if stored.startswith(HOME):
		return str(Path(os.path.expanduser(stored)))

	if not stored.startswith(PREFIX):
		return stored

	name, _, rest = stored[len(PREFIX) :].partition("/")

	for known_name, root in roots() if known is None else known:
		if known_name != name.lower():
			continue

		return str(Path(root, *[piece for piece in rest.split("/") if piece]))

	return stored


def portable(stored: str) -> bool:
	return stored.startswith((HOME, PREFIX))


def shareable(path: str, known: Roots | None = None) -> bool:
	return portable(contract(path, known))


#
# Whole databases
#


def _rekey(
	data: Projects, settings: Settings | None, convert: Any, copy: bool
) -> Projects:
	if not enabled(settings):
		return data

	known = roots(settings)

	moved: Projects = {}

	for key, project in data.items():
		wanted = convert(key, known)

		if wanted in moved:
			wanted = key

		entry: Project = dict(project) if copy else project  # pyright: ignore[reportAssignmentType]
		entry["path"] = wanted

		moved[wanted] = entry

	return moved


def expand_paths(data: Projects, settings: Settings | None = None) -> Projects:
	return _rekey(data, settings, expand, copy=False)


def contract_paths(data: Projects, settings: Settings | None = None) -> Projects:
	return _rekey(data, settings, contract, copy=True)
