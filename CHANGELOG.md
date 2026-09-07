# Changelog

## [1.2.0]

### Added

- `doctor`, `doc`, `health`, `healthcheck`, `hc`, a report on what is wrong with the
  database, and `fix`, `repair`, `migrate`, which repairs it as one undoable change.
- `[sync]`, portable paths. Store the database in something like Git, Syncthing, etc.
- A project now records which machines have it on disk and carries a `fingerprint`,
  the repository's root commit, which is the same on every machine that ever cloned it.

## [1.1.0]

### Added

- `todo`, `td`, a todo list with its own IDs, numbering and undo. Add, rename, note,
  status, done, reopen, check, clear and remove.
- Ability to move the settings file position directly.

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
