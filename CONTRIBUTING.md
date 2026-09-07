# Contributing

Thanks for taking the time! Bug reports, ideas and patches are all welcome.

## Getting set up

Tracker has no runtime dependencies. Python 3.11+ is all it needs.

```sh
git clone https://github.com/MattFor/simple-project-tracker
cd tracker

python -m venv .venv
. .venv/bin/activate

pip install -e .
pip install ruff basedpyright pytest
```

Run it straight from the checkout with `python main.py <command>`, which keeps the
database and the settings inside the checkout (`data.pkl` and `my_settings.toml`).

## Before opening a pull request

```sh
ruff format .          # tabs, double quotes, 90 columns
ruff check .           # must be clean
basedpyright           # must report 0 errors and 0 warnings
pytest                 # must be green
python tests/run.py    # the same suite without pytest installed
```

`make check` runs all of it in one go. The CI runs the same on Linux and macOS against
Python 3.11, 3.12 etc., and builds the distribution.

If you want it automation:

```sh
pip install pre-commit
pre-commit install
```

## Where things live

| Path                      | What is in it                                              |
| ------------------------- | ---------------------------------------------------------- |
| `tracker/cli/app.py`      | Argument parsing: aliases, fusing, splitting into commands |
| `tracker/cli/commands.py` | One function per command, plus the shared `Context`        |
| `tracker/core/`           | Discovery, selection, identity, labels, storage, daemon    |
| `tracker/config/`         | Settings, defaults, paths, the TOML writer                 |
| `tracker/ui/`             | Rendering: tables, details, colour, help                   |
| `tracker/util/`           | Text, files and small helpers                              |
| `tracker/share/`          | Shipped `settings.toml`, `help.txt`, completions           |
| `man/tracker.1`           | The man page                                               |

## Adding a setting

1. Add it to `defaults()` in `tracker/config/defaults.py`, with a sane default please.
2. Add it to `tracker/share/settings.toml` with a comment saying what it does. The two are
   compared by a test.
3. If it takes one of a fixed set of values, add it to `CHOICES`. If it is a free form
   table, add it to `OPEN_TABLES`.
4. Document it in `tracker/share/help.txt`, `man/tracker.1` and the README when a user
   would look for it.
5. Add a test.

## Adding a command

1. Write `command_<name>` in `tracker/cli/commands.py`. Take a `Context`, take
   `list[str]`, return an exit code.
2. Register it in `COMMANDS` and `HANDLERS` in `tracker/cli/app.py`, plus `GREEDY`,
   `SUBJECT` or `ACTIONS` if it takes free text, a project before the command, or sub
   actions.
3. Give it a section in `tracker/share/help.txt`; a test asserts every command has one.
4. Decorate it with `@marks_used` if looking at a project through it counts as using it.

## Commits

Explain what you did, list it all. Who doesn't love verbose commits.
