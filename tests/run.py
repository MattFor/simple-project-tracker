#!/usr/bin/env python3

import io
import os
import sys
import inspect
import tempfile
import traceback

from typing import Any
from pathlib import Path
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))

os.environ["TRACKER_VIEW"] = str(Path(tempfile.mkdtemp()).resolve() / "view.json")


class Patch:
	def __init__(self) -> None:
		self._undo: list[Callable[[], None]] = []

	def setattr(self, target: Any, name: str, value: Any) -> None:
		previous = getattr(target, name)

		self._undo.append(lambda: setattr(target, name, previous))

		setattr(target, name, value)

	def chdir(self, path: str | os.PathLike[str]) -> None:
		previous = os.getcwd()

		self._undo.append(lambda: os.chdir(previous))

		os.chdir(path)

	def undo(self) -> None:
		for restore in reversed(self._undo):
			restore()

		self._undo.clear()


def main() -> int:
	import importlib

	from tracker.ui import ansi

	modules = sorted(path.stem for path in Path(__file__).parent.glob("test_*.py"))

	passed = 0
	failures: list[tuple[str, str, str]] = []

	for name in modules:
		module = importlib.import_module(f"tests.{name}")

		for attribute, function in sorted(vars(module).items()):
			if not attribute.startswith("test_") or not callable(function):
				continue

			arguments: dict[str, Any] = {}
			sandbox = Path(tempfile.mkdtemp()).resolve()

			environment = dict(os.environ)

			os.environ["TRACKER_VIEW"] = str(sandbox / "view.json")

			ansi.C.set_enabled(False)

			parameters = inspect.signature(function).parameters
			patch = Patch()

			if "tmp_path" in parameters:
				arguments["tmp_path"] = sandbox

			if "monkeypatch" in parameters:
				arguments["monkeypatch"] = patch

			said = io.StringIO()

			try:
				with redirect_stdout(said), redirect_stderr(said):
					_ = function(**arguments)

				passed += 1
			except Exception:
				failures.append(
					(f"{name}.{attribute}", traceback.format_exc(), said.getvalue())
				)
			finally:
				patch.undo()

				os.environ.clear()
				os.environ.update(environment)

	for name, error, said in failures:
		print(f"FAILED {name}\n{error}")

		if said.strip():
			print(f"--- what it printed ---\n{said.rstrip()}\n")

	print(f"{passed} passed, {len(failures)} failed")

	return 1 if failures else 0


if __name__ == "__main__":
	sys.exit(main())
