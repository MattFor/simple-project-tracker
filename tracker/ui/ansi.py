import os
import re
import sys

from typing import IO, final

_CODES = {
	"RESET": "\033[0m",
	"BOLD": "\033[1m",
	"DIM": "\033[2m",
	"RED": "\033[31m",
	"GREEN": "\033[32m",
	"YELLOW": "\033[33m",
	"BLUE": "\033[34m",
	"MAGENTA": "\033[35m",
	"CYAN": "\033[36m",
	"WHITE": "\033[37m",
	"GRAY": "\033[90m",
}

MARKUP = {
	"/": "RESET",
	"reset": "RESET",
	"b": "BOLD",
	"bold": "BOLD",
	"d": "DIM",
	"dim": "DIM",
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
}

_MARKUP = re.compile(r"\{(/|[A-Za-z]+)\}")


@final
class Palette:
	RESET: str = ""
	BOLD: str = ""
	DIM: str = ""
	RED: str = ""
	GREEN: str = ""
	YELLOW: str = ""
	BLUE: str = ""
	MAGENTA: str = ""
	CYAN: str = ""
	WHITE: str = ""
	GRAY: str = ""

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
