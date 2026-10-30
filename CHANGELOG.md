# Changelog

## [Unreleased]

### Added

- The browser edits: `n` adds a todo (on a project, one linked to it), `x` marks it done or open,
  `S` / `N` set the status / note of a todo or project, `R` / `D` rename / remove a todo, `u` undoes.
- The browser links: `@` on a todo then `@` on a project (or the other way) adds the `@mention`,
  `o` goes from a todo to its project and from a project to its todo.
- `output.branches` lists every `local` branch, or `all` with the remote ones, and their last
  commits in a project's details. `b` cycles it in the browser.

### Changed

- The browser wraps long lines in the detail pane instead of cutting them off, and says when
  there is more to scroll to with `J` / `K`.

## [1.3.0] - 23:34 CEST 26-10-2026

### Added

- A project browser in a terminal: the monitored folders as a tree, statuses and last changes.
- A todo named exactly after a project counts as being about it (just like `@mention` with `check`)

## [1.2.1] - 23:23 CEST 11-10-2026

### Added

- `t td add <name> n <note>` and `s <status>` set the note and status as the todo is
  added, instead of folding them into its name.
- A note or status for a todo that does not exist yet (`t td lexiglance n ...`) offers to
  add it.

### Fixed

- `t td <name> n <note>` with a name of more than one word, every word before the action
  is now the todo.
- A note or status that matched nothing said `edit did nothing`, it now names the command.

## [1.2.0] - 01:37 CEST 08-09-2026

### Added

- `doctor`, `doc`, `health`, `healthcheck`, `hc`, a report on what is wrong with the
  database, and `fix`, `repair`, `migrate`, which repairs it as one undoable change.
- `[sync]`, portable paths. Store the database in something like Git, Syncthing, etc.
- A project now records which machines have it on disk and carries a `fingerprint`,
  the repository's root commit, which is the same on every machine that ever cloned it.

## [1.1.0] - 10:33 CEST 30-08-2026

### Added

- `todo`, `td`, a todo list with its own IDs, numbering and undo. Add, rename, note,
  status, done, reopen, check, clear and remove.
- Ability to move the settings file position directly.

## [1.0.4] - 00:53 CEST 26-08-2026

- Added more colours, background colour support etc.
- Doing `tracker (project) edit note` (or an equivalent) without any arguments clears the
  note.

## [1.0.3] - 02:13 CEST 25-08-2026

### Fixed

- `edit` renders a note's colour markup in the line reporting the change.
- Making a directory a Git repository no longer hides every project beneath it.
- `tracker init` restores a project that is present again but still marked deleted.

### Added

- `scan.vanish_limit`, the most of a scanned path's projects a single scan may mark
  deleted before it is treated as a broken scan.

## [1.0.2]

### Changed

- literally nothing I skipped a version by accident I'm working on making sure that never
  happens again

## [1.0.1] - 13:05 CEST 24-08-2026

### Fixed

- `all` now lists every project ignoring `display.filter`.
- A renamed project directory no longer strands a running daemon on the old path,
- A rename is followed by `tracker init` inside the renamed directory.
- The launcher installed by `install.sh` explains itself when its source directory is gone
  instead of failing on a broken `cd`.

## [1.0.0] - 12:26 CEST 24-08-2026

First release! Scanning, the database, statuses and notes, selection by ID, TID, name,
path, range or status, list filters, the row format, relative times, the daemon, shell
completion, the settings file and the man page.

[1.3.0]: https://github.com/MattFor/simple-project-tracker/releases/tag/v1.3.0
[1.2.1]: https://github.com/MattFor/simple-project-tracker/releases/tag/v1.2.1
[1.2.0]: https://github.com/MattFor/simple-project-tracker/releases/tag/v1.2.0
[1.1.0]: https://github.com/MattFor/simple-project-tracker/releases/tag/v1.1.0
[1.0.4]: https://github.com/MattFor/simple-project-tracker/releases/tag/v1.0.4
[1.0.3]: https://github.com/MattFor/simple-project-tracker/releases/tag/v1.0.3
[1.0.2]: https://github.com/MattFor/simple-project-tracker/releases/tag/v1.0.2
[1.0.1]: https://github.com/MattFor/simple-project-tracker/releases/tag/v1.0.1
[1.0.0]: https://github.com/MattFor/simple-project-tracker/releases/tag/v1.0.0
