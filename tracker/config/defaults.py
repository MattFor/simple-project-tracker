from typing import Any

COLUMNS = (
	"tid",
	"id",
	"name",
	"path",
	"status",
	"last_touched",
	"last_used",
	"version",
	"language",
)

SORT_KEYS = (
	"id",
	"name",
	"path",
	"status",
	"last_touched",
	"time",
	"last_used",
	"used",
)

SORT_DIRECTIONS = ("ascending", "descending")

NOTE_POSITIONS = ("auto", "inline", "below")

RELATIVE_STYLES = ("long", "short")

CONFLICT_PREFERENCES = ("starts_with", "first_match", "frecency", "zoxide")

NUMBER_PREFERENCES = ("ask", "id", "tid")

NAME_STYLES = ("full", "truncate", "abbreviate")

IGNORED_DIRECTORIES = [
	".git",
	".venv",
	"venv",
	"dist",
	"build",
	"target",
	"__pycache__",
	"node_modules",
	".idea",
	".vscode",
	".mypy_cache",
	".pytest_cache",
	".ruff_cache",
]

IGNORED_FILES = [
	"*.pkl",
	"*.pyc",
	"*.pyo",
	"*.log",
	"*.lock",
	"*.pid",
	"*.tmp",
	"*.swp",
	"*.bak",
	"*.orig",
	"*.db",
	"*.sqlite",
	"*.sqlite3",
	".DS_Store",
]


def defaults() -> dict[str, Any]:
	return {
		"display": {
			"format": "",
			"list_limit": 20,
			"show_headers": True,
			"show_notes": True,
			"note_position": "auto",
			"note_min_width": 24,
			"columns": ["tid", "id", "name", "status", "last_touched"],
			"name_max_width": 0,
			"name_style": "truncate",
			"name_continuator": "...",
			"time_format": "%Y-%m-%d %H:%M:%S",
			"relative_times": False,
			"relative_style": "long",
			"vertical_separator": " | ",
			"horizontal_separator": "-",
			"max_width": 0,
			"filter": [],
			"status_colours": {
				"current": "green",
				"active": "green",
				"todo": "yellow",
				"planned": "yellow",
				"review-needed": "magenta",
				"blocked": "red",
				"shelf": "blue",
				"paused": "blue",
				"done": "cyan",
				"completed": "cyan",
				"final": "cyan",
				"maintenance": "cyan",
				"archived": "gray",
				"deleted": "gray",
				"unknown": "gray",
			},
		},
		"sorting": {
			"by": "last_touched",
			"direction": "descending",
			"status_order": [],
		},
		"projects": {
			"default_status": "unknown",
			"ignore": list(IGNORED_DIRECTORIES),
			"ignore_files": list(IGNORED_FILES),
			"auto_status": False,
			"auto_status_rules": {
				"dev": 7,
				"stable": 90,
				"archive": 0,
			},
			"conflict_resolution_preference": "starts_with",
			"number_preference": "ask",
			"confirm_destructive": True,
			"track_usage": True,
		},
		"scan": {
			"detect_git": True,
			"recursive": True,
			"stop_at_project": True,
			"follow_symlinks": False,
			"timestamps_skip_ignored": True,
			"detect_moves": True,
			"vanish_limit": 50,
			"exclude": [],
		},
		"output": {
			"colour": True,
			"compact": False,
			"absolute_paths": True,
		},
		"database": {
			"file": "data.pkl",
		},
		"logging": {
			"always_verbose": False,
		},
		"daemon": {
			"paths": [],
			"archive": True,
			"interval": 60,
			"timestamp_format": "%Y-%m-%d %H:%M:%S",
		},
	}


SECTION_TITLES = {
	"display": "Display",
	"sorting": "Sorting",
	"projects": "Projects",
	"scan": "Scanning",
	"output": "Output",
	"database": "Database",
	"logging": "Logging",
	"daemon": "Daemon",
}

CHOICES: dict[str, tuple[str, ...]] = {
	"display.name_style": NAME_STYLES,
	"display.note_position": NOTE_POSITIONS,
	"display.relative_style": RELATIVE_STYLES,
	"sorting.by": SORT_KEYS,
	"sorting.direction": SORT_DIRECTIONS,
	"projects.conflict_resolution_preference": CONFLICT_PREFERENCES,
	"projects.number_preference": NUMBER_PREFERENCES,
}

OPEN_TABLES = frozenset({"display.status_colours", "projects.auto_status_rules"})
