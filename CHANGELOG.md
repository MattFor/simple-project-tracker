# Changelog

## [1.1.0]

### Added

- `todo`, `td`, a todo list with its own IDs, numbering and undo. Add, rename, note,
  status, done, reopen, check, clear and remove, selected the way a project is and fused
  the same way: `t tda`, `t tdl`, `t tdd`.
- `[todos]` settings: `database`, `new_status`, `done_status`, `sort` and `newest_first`.
- `@name` in a todo note prints as `name#id:tid` in the colour of that project's status,
  `@(two words)` and `@12` too. One that names no project is left as written.
- A todo listing takes the filters `tracker list` takes.
- `check` reads both ways: the todos about a project, and the projects a todo names.
- `move`, `mv`, puts the settings, the database or the todo list somewhere else and
  points tracker at it. `t move` alone says where all three are.
- `[todos.display]`, the display settings the todo list alone uses. A key left out of it
  is inherited from `[display]` and then from the defaults, and only that way round:
  `[display]` never picks anything up from `[todos.display]`. `[todos.display.status_colours]`
  sits over `[display.status_colours]` one status at a time.
- The todo table takes a `format` of its own, and its columns may be named outright:
  `tid`, `id`, `name`, `status`, `created`, `updated`, `done_at` and `note`, with
  `last_touched` and `last_used` read as `created` and `updated` so a shared
  `display.columns` keeps working.
- `settings get` and `settings set` reach a nested table, `todos.display.columns` and
  `display.status_colours.todo` alike, shortened the usual way as `t.d.columns`. `get`
  says which setting an inherited value came from.

## [1.0.4]

- Added more colours, background colour support etc.
- Doing `tracker (project) edit note` (or an equivalent) without any arguments clears the
  note.

## [1.0.3]

### Fixed

- `edit` renders a note's colour markup in the line reporting the change.
- Making a directory a Git repository no longer hides every project beneath it.
- `tracker init` restores a project that is present again but still marked deleted.

### Added

- `scan.vanish_limit`, the most of a scanned path's projects a single scan may mark
  deleted before it is treated as a broken scan.

## [1.0.2]

### Changes

- literally nothing I skipped a version by accident I'm working on making sure that never
  happens again

## [1.0.1]

### Fixed

- `all` now lists every project ignoring `display.filter`.
- A renamed project directory no longer strands a running daemon on the old path,
- A rename is followed by `tracker init` inside the renamed directory.
- The launcher installed by `install.sh` explains itself when its source directory is gone
  instead of failing on a broken `cd`.

## [1.0.0]

First release! Scanning, the database, statuses and notes, selection by ID, TID, name,
path, range or status, list filters, the row format, relative times, the daemon, shell
completion, the settings file and the man page.
