# simple-project-tracker

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A simple, but very customizable tracker to keep track of your projects, their states and
your notes on them.

```
TID | ID | NAME                          | STATUS  | LAST TOUCHED | NOTE
--- | -- | ----------------------------- | ------- | ------------ | ---------------------
1   | 8  | tracker                       | dev     | 1m ago       | release 1.0.0 today
2   | 3  | von-neumann-machine-simulator | dev     | 23m ago      | review saturday
3   | 26 | discord-profile-studio        | stable  | 1h ago
```

## Contents

- [Install](#install)
- [Commands](#commands)
- [Todos](#todos)
- [Selecting projects](#selecting-projects)
- [Configuration](#configuration)
- [Development](#development)
- [License](#license)

## Install

```sh
./install.sh             # ~/.local
sudo ./install.sh        # /usr/local
./install.sh --daemon    # also install the daemon autostart entry
./install.sh --uninstall
```

Python 3.11+. Then `t init ~/(your project directory)` to fill the database.

## Commands

| Command      | Aliases           | What it does                                                         |
|--------------|-------------------|----------------------------------------------------------------------|
| `list`       | `l`, `ls`         | List projects, with search, regex, filters and setting overrides     |
| `check`      | `c`, `cc`, `info` | Everything about a project: git state, size, language, version, note |
| `add`        | `a`               | Track a project, or scan a directory and track what is inside        |
| `remove`     | `rm`, `r`, `del`  | Stop tracking projects (files untouched)                             |
| `forget`     | `ignore`          | Stop tracking and keep scans from finding it again                   |
| `edit`       | `e`               | Change a `status` or a `note`                                        |
| `note`       | `n`, `sn`         | Set a note without naming the field                                  |
| `status`     | `st`, `ss`        | List statuses, set one, or move every project from one to another    |
| `todo`       | `td`, `todos`     | A todo list of its own: add, edit, status, note, done, clear         |
| `init`       | `i`, `scan`       | Scan a directory and merge the result into the database              |
| `path`       | `p`, `where`      | Print a project's path, e.g. `cd "$(t path tracker)"`                |
| `undo`       | `u`, `revert`     | Take back the last change, undo again to put it back                 |
| `move`       | `mv`              | Move the settings, database or todo list, and point tracker at it    |
| `stats`      | `summary`         | Totals, a breakdown by status, most and least recently touched       |
| `settings`   | `s`, `config`     | Show, edit, get or set the configuration                             |
| `completion` |                   | Print a shell completion script for bash, zsh or fish                |
| `daemon`     | `d`, `bg`         | `start`, `stop`, `restart`, `status`, `log`, `run`                   |

The project goes before or after the command, whichever reads better, and a command fuses
with its own action:

```sh
t 12 es blocked        # edit status  also: t edit 12 status blocked
t 12 sn review sunday  # set note     also: t note 12 review sunday
t dst                  # daemon status
t sset ll 30           # settings set display.list_limit 30
```

A bare word defaults to a project lookup.

```sh
t tra          # the check view for tracker
t stable       # nothing is called that, so every stable project
t all          # everything with no limit and no filter
```

For more information do: `t help`, `t help <command>` or `t help <topic>`. The full guide
is within `man tracker`.

## Todos

List of notes that's separate from the main project database.

```sh
t td                          # the whole list
t td add write the changelog  # the rest of the line is the name
t td 3 done                   # also: t td done 3
t td 3 st blocked             # any status you like
t td 3 n waiting on review    # and a note under it
t td list s:todo              # only what is still open
t td clear                    # drop every finished one
t td undo                     # take the last change back
```

```
TID | ID | NAME                  | STATUS  | CREATED    | NOTE
--- | -- | --------------------- | ------- | ---------- | ----------------------
1   | 1  | write the changelog   | todo    | 2m ago     | blocked on the release
2   | 2  | fix the daemon logs   | done    | 1h ago
3   | 3  | ship the todo feature | review  | 1h ago     | shipped on a sunday
3 todos, 2 left  (2 todo, 1 done)
```

A todo is selected exactly the same way a project is, and the same short forms apply.

A note may point at a project with `@name`, printed as `name#id:tid` in that project's
status colour. `t check <project>` then lists the todos about it, and `t td check <todo>`
the projects it names.

## Selecting projects

| Selector    | Means                                                     |
|-------------|-----------------------------------------------------------|
| `12`        | ID or TID 12                                              |
| `i:12`      | The permanent ID, `id:` and `#12` too                     |
| `t:12`      | The temporary ID, `tid:`, `@12` and `:12` too             |
| `3-7`,`5+3` | A range, either direction, or a project and the next few  |
| `s:blocked` | Every project with that status, `st:` and `status:` too   |
| `name`      | Exact or partial name, or a path, tab completion included |
| `all`       | Every tracked project limits and display filters off      |

A temporary ID is the index of the latest output.

When a partial name matches several projects, it's settled by
`projects.conflict_resolution_preference`.

## Configuration

```sh
t settings                    # everything (default deviations marked)
t settings edit               # open in $EDITOR
t sset list_limit 30          # rewrites that one line
t list ll=5 rt=true           # override for one command only
```

A setting can be named in full, by its bare name, by a prefix, by the start of every word
or by its initials, with the section shortening the same way: `display.list_limit`,
`list_limit`, `list_lim`, `l_l`, `ll`, `d.ll`. Ambiguities are reported.

| Setting                             | What it does                                                |
|-------------------------------------|-------------------------------------------------------------|
| `display.filter`                    | Filters every listing but `all`, e.g. `["-s:archive"]`      |
| `display.columns`, `display.format` | Which columns, or a row layout of your own                  |
| `display.relative_times`            | `2 days ago` instead of a timestamp                         |
| `display.name_max_width`            | Shorten long names, `truncate` or `abbreviate`              |
| `sorting.by`, `sorting.direction`   | `last_touched`, `last_used`, `name`, `status`, `id`, `path` |
| `projects.ignore`, `.ignore_files`  | Directories and files that never count as your own work     |
| `projects.auto_status`              | Status from how long ago a project was touched              |
| `scan.detect_moves`                 | A moved project keeps its entry instead of looking deleted  |
| `daemon.paths`, `daemon.interval`   | What the background scanner watches, and how often          |
| `todos.new_status`, `.done_status`  | What a new todo is called, and what `done` and `clear` use  |
| `todos.sort`, `todos.newest_first`  | How the todo list is ordered                                |
| `[todos.display]`                   | Display settings the todo list alone uses                   |

Notes can colour themselves: `t note 12 {red}broken{/} since friday`.

## Development

```sh
make dev      # editable install plus ruff, basedpyright, pytest
make check    # format, lint, types and tests (what CI runs)
```

## Disclosure

LLMs were used to:

- write tests
- write the man page
- write the help section
- check for critical issues and annotation errors

**HOWEVER**, the output was then manually reviewed and issues were fixed by a human.  
I wanted to get this project out asap as I really needed it :P

## License

MIT [LICENSE](LICENSE).  
By MattFor.
