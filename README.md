# Tracker

Simple tracker that tracks the projects in your directories, their versions and allows you to track their
status/completion progress.

## Install

From a checkout, which keeps the settings and the database next to the source:

```sh
./install.sh
./install.sh --daemon
./install.sh --uninstall
```

Requires Python 3.11+ and nothing else.

## Commands

| Command    | Aliases           | What it does                                                         |
|------------|-------------------|----------------------------------------------------------------------|
| `list`     | `l`, `ls`         | List projects, with search, regex, filters and setting overrides     |
| `check`    | `c`, `cc`, `info` | Everything about a project: git state, size, language, version, note |
| `add`      | `a`               | Track a project, or scan a directory and track what is inside        |
| `remove`   | `rm`, `r`, `del`  | Stop tracking projects, nothing is deleted from disk                 |
| `edit`     | `e`               | Change a `status` or a `note`                                        |
| `note`     | `n`               | Set a note, without naming the field                                 |
| `status`   | `st`              | Set a status, without naming the field                               |
| `init`     | `i`, `scan`       | Scan a directory and merge the result into the database              |
| `path`     | `p`, `where`      | Print a project's path, e.g. `cd "$(t path tracker)"`                |
| `stats`    | `summary`         | Totals, a breakdown by status, most and least recently touched       |
| `settings` | `s`, `config`     | Show, edit, get or set the configuration                             |
| `daemon`   | `d`, `bg`         | `start`, `stop`, `restart`, `status`, `log`, `run`                   |

Commands that work on a project take it before or after the command, whichever reads better:

```
t edit 12 note review sunday
t 12 edit note review sunday
t 12 note review sunday
t 12 n review sunday
t tracker st current
```

`status` shortens to `s`/`st` and `note` to `n`/`nt`.

### Selecting projects

Anything that takes a project accepts an ID, a TID from the current view, a name, a path, or a range:

```
t check 12       # ID or TID 12
t check id:12    # force the permanent ID
t check tid:12   # force the temporary ID
t check '#12'    # same as id:12, quoted
t check @12      # same as tid:12
t edit 3-7 status completed
t edit 5+3 status shelf
t edit all status archived
```

A bare `#12` never reaches tracker, the shell strips it as a comment, so use
`id:12` or quote it.

## Configuration

Installed, tracker reads `~/.config/tracker/settings.toml` and falls back to the defaults shipped with the package.
`t settings edit` and `t settings set` create your copy the first time they run, so nothing is ever written inside the
install prefix.

From a checkout it reads `my_settings.toml`, then `tracker/share/settings.toml`, and keeps `data.pkl` in the checkout.

```sh
t settings                                  # show everything
t settings set display.list_limit 30        # rewrites that one line
t settings edit                             # open in $EDITOR
t list sorting.by=name output.compact=true  # override for one command only
```

## Roadmap

- [x] daemon that keeps the database up to date on its own
- [x] proper folder structure and names
- [x] a partial or malformed `my_settings.toml` no longer breaks everything
- [x] show project versions inferred from the language config file (`pyproject.toml`, `Cargo.toml`, `package.json`, ...)
- [x] mention the codeberg mirror
- [ ] upload to xbps
- [ ] possible zoxide integration for conflicting matches

## Note

LLMs were used to write the man page and help section, but the output was then manually reviewed.

## License

MIT [LICENSE](LICENSE)

By MattFor
