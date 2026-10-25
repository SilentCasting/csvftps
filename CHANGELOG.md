# Changelog

## [1.1.0] - 2026-10-25

### Added
- Excel support: `.xlsx` and `.xlsm` can be the input, `.xlsx` the output,
  in any mix with CSV. The format follows the file extension.
- `[excel] sheet` setting (and an "Excel sheet" field in the app) to read a
  sheet by name or number; the first sheet is used by default.
- Excel output keeps numbers as numbers, makes header rows bold and freezes
  the first row. Text starting with `=` is stored as text, never as a formula.
- A clear message when the input or output is open in Excel or another program.
- `examples/input.xlsx`.

### Changed
- The app's file pickers and labels say "file" instead of "CSV" and offer
  Excel workbooks.

## [1.0.0] - 2026-10-12

Complete rewrite of the original 2022 script into a full app.

### Added
- Desktop app built with CustomTkinter: light/dark theme, file, conversion
  and server settings, Start/Stop schedule, Run once, Convert only,
  Test connection and a live log. `--start` begins the schedule on launch.
- Command line tool `csvftps` with `init`, `run` (`--once`, `--no-upload`,
  `--interval`), `convert`, `set-password` and `test`.
- TOML settings file shared by the app and the CLI, with checks and clear
  error messages.
- Configurable conversion: column by index or name, any number of ranges,
  empty/`NULL` values, header markers, delimiter and encodings. The defaults
  give exactly the same result as the original script.
- Password in the system keyring or the `CSVFTPS_PASSWORD` variable.
- Tests, CI on Windows and Linux, and a ready-to-run `.exe` on every release.

### Changed
- The server, login and password are no longer asked for on every run.
- Uploads are encrypted end to end (`PROT P`) and the server certificate is
  verified; it can be turned off for self-signed servers.
- A failed run (network down, file locked, bad value) is logged and the
  schedule carries on instead of the script crashing.
- Upload errors are retried, and files that already went up are not sent again.
- The converted CSV is written to a temp file and then moved into place, so a
  half-written file is never uploaded.
- Non-numeric values and short rows are kept as they are and reported,
  instead of stopping the whole run.

## [0.1.0] - 2022-02-10

- First version: a script that grouped one CSV column into size ranges and
  uploaded the result with three other files every 10 minutes.
