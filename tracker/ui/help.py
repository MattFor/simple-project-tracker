from tracker.ui.ansi import C

from tracker.config import paths
from tracker.config.metadata import Metadata


def print_help(project: Metadata) -> None:
	try:
		text = paths.help_file().read_text(encoding="utf-8")
	except OSError as error:
		print(f"[ERROR] could not read the help file: {error}")
		print(f"it should live at {paths.help_file()}")
		return

	replacements = {
		"PROJECT_NAME": project.name.capitalize(),
		"PROJECT_VERSION": project.version,
		"PROJECT_AUTHOR": project.author,
		"BOLD": C.BOLD,
		"DIM": C.DIM,
		"RED": C.RED,
		"CYAN": C.CYAN,
		"GRAY": C.GRAY,
		"BLUE": C.BLUE,
		"GREEN": C.GREEN,
		"WHITE": C.WHITE,
		"YELLOW": C.YELLOW,
		"MAGENTA": C.MAGENTA,
		"RESET": C.RESET,
	}

	for key, value in replacements.items():
		text = text.replace(f"{{{key}}}", str(value))

	print(text)
