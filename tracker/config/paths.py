import os

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PACKAGE_ROOT.parent

SHARE_DIR = PACKAGE_ROOT / "share"
SYSTEM_SHARE_DIRS = (Path("/usr/share/tracker"), Path("/usr/local/share/tracker"))

HELP_NAME = "help.txt"
SETTINGS_NAME = "settings.toml"
LOCAL_SETTINGS_NAME = "my_settings.toml"

DEFAULT_DATA_FILE = "data.pkl"


def in_source_tree() -> bool:
	return (PROJECT_ROOT / "pyproject.toml").is_file()


#
# Shipped files
#


def share_dirs() -> tuple[Path, ...]:
	override = os.environ.get("TRACKER_SHARE")

	directories = [Path(os.path.expanduser(override))] if override else []
	directories.append(SHARE_DIR)
	directories.extend(SYSTEM_SHARE_DIRS)

	return tuple(directories)


def bundled_file(name: str) -> Path:
	for directory in share_dirs():
		candidate = directory / name

		if candidate.is_file():
			return candidate

	return SHARE_DIR / name


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
	return PROJECT_ROOT if in_source_tree() else Path.home()


def database_dir() -> Path:
	return PROJECT_ROOT if in_source_tree() else data_dir()


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
			candidate = PROJECT_ROOT / name

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
