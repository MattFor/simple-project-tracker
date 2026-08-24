# Changelog

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
