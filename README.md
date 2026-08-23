# Tracker

Simple tracker that tracks the projects in your directories, their versions and allows you to track their
status/completion progress.

## Install

As yourself, which points a launcher at the checkout and keeps the settings and the database next to the source:

```sh
./install.sh
./install.sh --daemon
./install.sh --uninstall
```

Or, to install to /usr/local

```sh
sudo ./install.sh
```

Requires Python 3.11+ and nothing else.

## Commands

| Command      | Aliases           | What it does                                                         |
|--------------|-------------------|----------------------------------------------------------------------|
| `list`       | `l`, `ls`         | List projects, with search, regex, filters and setting overrides     |
| `check`      | `c`, `cc`, `info` | Everything about a project: git state, size, language, version, note |
| `add`        | `a`               | Track a project, or scan a directory and track what is inside        |
| `remove`     | `rm`, `r`, `del`  | Stop tracking projects, nothing is deleted from disk                 |
| `forget`     | `ignore`          | Stop tracking and keep scans from finding it again                   |
| `edit`       | `e`               | Change a `status` or a `note`                                        |
| `note`       | `n`               | Set a note, without naming the field                                 |
| `status`     | `st`              | List statuses, set one, or move every project from one to another    |
| `init`       | `i`, `scan`       | Scan a directory and merge the result into the database              |
| `path`       | `p`, `where`      | Print a project's path, e.g. `cd "$(t path tracker)"`                |
| `stats`      | `summary`         | Totals, a breakdown by status, most and least recently touched       |
| `settings`   | `s`, `config`     | Show, edit, get or set the configuration                             |
| `completion` |                   | Print a shell completion script for bash, zsh or fish                |
| `daemon`     | `d`, `bg`         | `start`, `stop`, `restart`, `status`, `log`, `run`                   |

Commands that work on a project take it before or after the command, whichever reads better:

```
t edit 12 note review sunday
t 12 edit note review sunday
t 12 note review sunday
t 12 n review sunday
t tracker st current
```

`status` shortens to `s`/`st` and `note` to `n`/`nt`.

Everything after a `--` is text rather than options or commands, for a note that starts with a dash or contains a
command name:

```
t note 12 -- --verbose is not a flag here
```

### Selecting projects

Anything that takes a project accepts an ID, a TID from the current view, a name, a path, or a range:

```
t check 12          # ID or TID 12
t check i:12        # force the permanent ID, id:12 also works
t check t:12        # force the temporary ID, tid:12 also works
t check ./project   # a path, tab completion included
t check s:blocked   # every project with that status
t edit 3-7 status completed
t edit 5+3 status shelf
t edit t:3-7 status shelf
t edit all status archived
```

### Tab completion

```sh
eval "$(tracker completion bash)"   # ~/.bashrc
eval "$(tracker completion zsh)"    # ~/.zshrc
tracker completion fish > ~/.config/fish/completions/tracker.fish
```

Completes command names and tracked project names, for both `tracker` and `t`.

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

- [ ] upload to xbps
- [ ] possible zoxide integration for conflicting matches


## Disclosure

LLMs were used to write the man page, help section and checked for annotation errors, but the output was then manually reviewed.

## License

MIT [LICENSE](LICENSE)

By MattFor
