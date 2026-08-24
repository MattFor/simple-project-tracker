import sys


def confirm(question: str, *, assume_yes: bool = False, required: bool = True) -> bool:
	if assume_yes:
		return True

	if not required:
		return True

	if not sys.stdin.isatty():
		print("[ERROR] refusing to run without confirmation; pass --yes")
		return False

	try:
		answer = input(f"{question} [y/N] ").strip().lower()
	except (EOFError, KeyboardInterrupt):
		print()
		return False

	return answer in ("y", "yes")
