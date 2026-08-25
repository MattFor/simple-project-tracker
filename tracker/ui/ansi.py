import os
import re
import sys

from typing import IO, final

_CODES = {
	"RESET": "\033[0m",
	"BOLD": "\033[1m",
	"DIM": "\033[2m",
	"ITALIC": "\033[3m",
	"UNDERLINE": "\033[4m",
	"BLINK": "\033[5m",
	"INVERT": "\033[7m",
	"STRIKE": "\033[9m",
	"BLACK": "\033[30m",
	"RED": "\033[31m",
	"GREEN": "\033[32m",
	"YELLOW": "\033[33m",
	"BLUE": "\033[34m",
	"MAGENTA": "\033[35m",
	"CYAN": "\033[36m",
	"WHITE": "\033[37m",
	"GRAY": "\033[90m",
	"BRIGHT_RED": "\033[91m",
	"BRIGHT_GREEN": "\033[92m",
	"BRIGHT_YELLOW": "\033[93m",
	"BRIGHT_BLUE": "\033[94m",
	"BRIGHT_MAGENTA": "\033[95m",
	"BRIGHT_CYAN": "\033[96m",
	"BRIGHT_WHITE": "\033[97m",
	"BG_BLACK": "\033[40m",
	"BG_RED": "\033[41m",
	"BG_GREEN": "\033[42m",
	"BG_YELLOW": "\033[43m",
	"BG_BLUE": "\033[44m",
	"BG_MAGENTA": "\033[45m",
	"BG_CYAN": "\033[46m",
	"BG_WHITE": "\033[47m",
}

MARKUP = {
	"/": "RESET",
	"reset": "RESET",
	"b": "BOLD",
	"bold": "BOLD",
	"d": "DIM",
	"dim": "DIM",
	"i": "ITALIC",
	"italic": "ITALIC",
	"ul": "UNDERLINE",
	"underline": "UNDERLINE",
	"blink": "BLINK",
	"inv": "INVERT",
	"invert": "INVERT",
	"s": "STRIKE",
	"strike": "STRIKE",
	"black": "BLACK",
	"r": "RED",
	"red": "RED",
	"g": "GREEN",
	"green": "GREEN",
	"y": "YELLOW",
	"yellow": "YELLOW",
	"u": "BLUE",
	"blue": "BLUE",
	"m": "MAGENTA",
	"magenta": "MAGENTA",
	"c": "CYAN",
	"cyan": "CYAN",
	"w": "WHITE",
	"white": "WHITE",
	"k": "GRAY",
	"gray": "GRAY",
	"grey": "GRAY",
	"br-r": "BRIGHT_RED",
	"br-red": "BRIGHT_RED",
	"br-g": "BRIGHT_GREEN",
	"br-green": "BRIGHT_GREEN",
	"br-y": "BRIGHT_YELLOW",
	"br-yellow": "BRIGHT_YELLOW",
	"br-b": "BRIGHT_BLUE",
	"br-blue": "BRIGHT_BLUE",
	"br-m": "BRIGHT_MAGENTA",
	"br-magenta": "BRIGHT_MAGENTA",
	"br-c": "BRIGHT_CYAN",
	"br-cyan": "BRIGHT_CYAN",
	"br-w": "BRIGHT_WHITE",
	"br-white": "BRIGHT_WHITE",
	"bg-k": "BG_BLACK",
	"bg-black": "BG_BLACK",
	"bg-r": "BG_RED",
	"bg-red": "BG_RED",
	"bg-g": "BG_GREEN",
	"bg-green": "BG_GREEN",
	"bg-y": "BG_YELLOW",
	"bg-yellow": "BG_YELLOW",
	"bg-b": "BG_BLUE",
	"bg-blue": "BG_BLUE",
	"bg-m": "BG_MAGENTA",
	"bg-magenta": "BG_MAGENTA",
	"bg-c": "BG_CYAN",
	"bg-cyan": "BG_CYAN",
	"bg-w": "BG_WHITE",
	"bg-white": "BG_WHITE",
}

_MARKUP = re.compile(r"\{(/|[A-Za-z0-9-]+)\}")


@final
class Palette:
	RESET: str = ""
	BOLD: str = ""
	DIM: str = ""
	ITALIC: str = ""
	UNDERLINE: str = ""
	BLINK: str = ""
	INVERT: str = ""
	STRIKE: str = ""
	BLACK: str = ""
	RED: str = ""
	GREEN: str = ""
	YELLOW: str = ""
	BLUE: str = ""
	MAGENTA: str = ""
	CYAN: str = ""
	WHITE: str = ""
	GRAY: str = ""
	BRIGHT_RED: str = ""
	BRIGHT_GREEN: str = ""
	BRIGHT_YELLOW: str = ""
	BRIGHT_BLUE: str = ""
	BRIGHT_MAGENTA: str = ""
	BRIGHT_CYAN: str = ""
	BRIGHT_WHITE: str = ""
	BG_BLACK: str = ""
	BG_RED: str = ""
	BG_GREEN: str = ""
	BG_YELLOW: str = ""
	BG_BLUE: str = ""
	BG_MAGENTA: str = ""
	BG_CYAN: str = ""
	BG_WHITE: str = ""

	def __init__(self, enabled: bool = True) -> None:
		self.enabled = True
		self.set_enabled(enabled)

	def set_enabled(self, enabled: bool) -> None:
		self.enabled = enabled

		for name, code in _CODES.items():
			setattr(self, name, code if enabled else "")

	def paint(self, text: str, colour: str) -> str:
		if not self.enabled or not colour:
			return text

		code = _CODES.get(colour.strip().upper())

		if not code:
			return text

		return f"{code}{text}{self.RESET}"


C = Palette(True)


def markup(text: str, base: str = "") -> str:
	if "{" not in text:
		return text

	fallback = _CODES.get(base.strip().upper(), "") if base else ""

	def replace(match: re.Match[str]) -> str:
		name = MARKUP.get(match.group(1).lower())

		if name is None:
			return match.group(0)

		if not C.enabled:
			return ""

		if name == "RESET":
			return _CODES["RESET"] + fallback

		return _CODES[name]

	return _MARKUP.sub(replace, text)


def configure(setting: bool = True, stream: IO[str] | None = None) -> None:
	output: IO[str] = sys.stdout if stream is None else stream

	if os.environ.get("FORCE_COLOR"):
		C.set_enabled(bool(setting))
		return

	if os.environ.get("NO_COLOR") is not None or os.environ.get("TERM") == "dumb":
		C.set_enabled(False)
		return

	try:
		interactive = output.isatty()
	except (AttributeError, ValueError):
		interactive = False

	C.set_enabled(bool(setting) and interactive)
