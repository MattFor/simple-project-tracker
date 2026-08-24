#!/usr/bin/env python3

import os
import sys
import inspect
import tempfile
import traceback

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))

os.environ["TRACKER_VIEW"] = str(Path(tempfile.mkdtemp()).resolve() / "view.json")


def main() -> int:
	import importlib

	from tracker.ui import ansi

	modules = sorted(path.stem for path in Path(__file__).parent.glob("test_*.py"))

	passed = 0
	failures: list[tuple[str, str]] = []

	for name in modules:
		module = importlib.import_module(f"tests.{name}")

		for attribute, function in sorted(vars(module).items()):
			if not attribute.startswith("test_") or not callable(function):
				continue

			arguments = {}
			sandbox = Path(tempfile.mkdtemp()).resolve()

			os.environ["TRACKER_VIEW"] = str(sandbox / "view.json")

			ansi.C.set_enabled(False)

			if "tmp_path" in inspect.signature(function).parameters:
				arguments["tmp_path"] = sandbox

			try:
				_ = function(**arguments)
				passed += 1
			except Exception:
				failures.append((f"{name}.{attribute}", traceback.format_exc()))

	for name, error in failures:
		print(f"FAILED {name}\n{error}")

	print(f"{passed} passed, {len(failures)} failed")

	return 1 if failures else 0


if __name__ == "__main__":
	sys.exit(main())
