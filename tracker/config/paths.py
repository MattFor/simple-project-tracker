import os

from pathlib import Path

_INSTALLED_PACKAGE = Path(__file__).resolve().parent.parent

SYSTEM_SHARE_DIRS = (Path("/usr/share/tracker"), Path("/usr/local/share/tracker"))

HELP_NAME = "help.txt"
SETTINGS_NAME = "settings.toml"
LOCAL_SETTINGS_NAME = "my_settings.toml"

DEFAULT_DATA_FILE = "data.pkl"


#
# Where the package lives
#


def _inode(path: Path) -> tuple[int, int] | None:
	try:
		stats = path.stat()
	except OSError:
		return None

	return stats.st_dev, stats.st_ino


_PACKAGE_INODE = _inode(_INSTALLED_PACKAGE)

_recovered: dict[str, Path] = {}


def _find_moved_package() -> Path | None:
	"""The daemon outlives a rename of the directory it was started from."""
	if _PACKAGE_INODE is None:
		return None

	known = _recovered.get("package")

	if known is not None and _inode(known) == _PACKAGE_INODE:
		return known

	try:
		current = Path.cwd()
	except OSError:
		return None

	for candidate in (current / _INSTALLED_PACKAGE.name, current):
		if _inode(candidate) == _PACKAGE_INODE:
			_recovered["package"] = candidate

			return candidate

	return None


def package_root() -> Path:
	if _inode(_INSTALLED_PACKAGE) == _PACKAGE_INODE:
		return _INSTALLED_PACKAGE

	return _find_moved_package() or _INSTALLED_PACKAGE


def project_root() -> Path:
	return package_root().parent


def share_dir() -> Path:
	return package_root() / "share"


def in_source_tree() -> bool:
	return (project_root() / "pyproject.toml").is_file()


#
# Shipped files
#


def share_dirs() -> tuple[Path, ...]:
	override = os.environ.get("TRACKER_SHARE")

	directories = [Path(os.path.expanduser(override))] if override else []
	directories.append(share_dir())
	directories.extend(SYSTEM_SHARE_DIRS)

	return tuple(directories)


def bundled_file(name: str) -> Path:
	for directory in share_dirs():
		candidate = directory / name

		if candidate.is_file():
			return candidate

	return share_dir() / name


def help_file() -> Path:
	return bundled_file(HELP_NAME)


#
# Directories
#


def config_dir() -> Path:
	base = os.environ.get("XDG_CONFIG_HOME")

	return (Path(base) if base else Path.home() / ".config") / "tracker"


def data_dir() -> Path:
	base = os.environ.get("XDG_DATA_HOME")

	return (Path(base) if base else Path.home() / ".local" / "share") / "tracker"


def state_dir() -> Path:
	base = os.environ.get("XDG_STATE_HOME")

	return (Path(base) if base else Path.home() / ".local" / "state") / "tracker"


def working_dir() -> Path:
	return project_root() if in_source_tree() else Path.home()


def database_dir() -> Path:
	return project_root() if in_source_tree() else data_dir()


def resolve(path: str | os.PathLike[str], base: Path | None = None) -> Path:
	resolved = Path(os.path.expanduser(str(path)))

	if not resolved.is_absolute():
		resolved = (base or working_dir()) / resolved

	return resolved


#
# Settings
#


def user_settings_file() -> Path:
	return config_dir() / SETTINGS_NAME


def settings_file() -> Path:
	override = os.environ.get("TRACKER_SETTINGS")

	if override:
		return resolve(override)

	if in_source_tree():
		for name in (LOCAL_SETTINGS_NAME, SETTINGS_NAME):
			candidate = project_root() / name

			if candidate.is_file():
				return candidate

	user = user_settings_file()

	if user.is_file():
		return user

	return bundled_file(SETTINGS_NAME)


def create_user_settings() -> Path:
	target = user_settings_file()

	if target.is_file():
		return target

	template = bundled_file(SETTINGS_NAME)

	try:
		target.parent.mkdir(parents=True, exist_ok=True)
		_ = target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
	except OSError as error:
		print(f"[ERROR] could not create {target}: {error}")

	return target


def editable_settings_file() -> Path:
	current = settings_file()

	if current != bundled_file(SETTINGS_NAME):
		return current

	return create_user_settings()


#
# Database and daemon
#


def data_file(configured: str | None = None) -> Path:
	chosen = os.environ.get("TRACKER_DATA") or configured or DEFAULT_DATA_FILE

	return resolve(chosen, database_dir())


def view_file() -> Path:
	override = os.environ.get("TRACKER_VIEW")

	if override:
		return resolve(override)

	return state_dir() / "view.json"


def daemon_pid_file() -> Path:
	return state_dir() / "daemon.pid"


def daemon_log_file() -> Path:
	return state_dir() / "daemon.log"
