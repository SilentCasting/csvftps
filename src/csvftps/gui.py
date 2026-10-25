"""Desktop app: pick the CSV or Excel file, set the rules and the server, then press Start."""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from csvftps import __version__
from csvftps import config as settings
from csvftps.config import Config, ConfigError, Range
from csvftps.credentials import CredentialsError, delete_password, get_password, set_password
from csvftps.runner import RunError, RunResult, run_forever, run_once
from csvftps.upload import UploadError, test_connection

ASSETS = Path(__file__).parent / "assets"
ENCODINGS = ["utf-8-sig", "utf-8", "cp1251", "cp1252", "latin-1", "utf-16"]
LOG_COLORS = {"WARNING": ("#9a6700", "#d29922"), "ERROR": ("#cf222e", "#f85149")}
MAX_LOG_LINES = 2000
MUTED = ("gray35", "gray65")

log = logging.getLogger("csvftps")


class QueueHandler(logging.Handler):
    """Hands log records from any thread to the window, which shows them in the log box."""

    def __init__(self, events: queue.Queue) -> None:
        super().__init__()
        self.events = events
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.events.put(("log", record.levelname, self.format(record)))


class RangeRow:
    """One line in the ranges editor: from, to, label and a remove button."""

    def __init__(self, parent: ctk.CTkFrame, row: int, item: Range, on_remove) -> None:
        self.low = ctk.CTkEntry(parent, width=80, placeholder_text="−∞")
        self.high = ctk.CTkEntry(parent, width=80, placeholder_text="+∞")
        self.label = ctk.CTkEntry(parent, placeholder_text="label")
        for entry, value in ((self.low, item.min), (self.high, item.max), (self.label, item.label)):
            if value is not None and value != "":
                entry.insert(0, _number_text(value) if isinstance(value, float | int) else value)
        remove = ctk.CTkButton(
            parent,
            text="✕",
            width=28,
            fg_color="transparent",
            text_color=MUTED,
            hover_color=("gray85", "gray25"),
            command=lambda: on_remove(self),
        )
        self.widgets = [self.low, self.high, self.label, remove]
        self.place(row)

    def place(self, row: int) -> None:
        for column, widget in enumerate(self.widgets):
            widget.grid(row=row, column=column, padx=(0, 6), pady=3, sticky="ew" if column == 2 else "")

    def destroy(self) -> None:
        for widget in self.widgets:
            widget.destroy()

    def read(self, number: int) -> Range | None:
        low, high, label = self.low.get().strip(), self.high.get().strip(), self.label.get()
        if not (low or high or label):
            return None  # an empty line is simply ignored
        return Range(
            label=label,
            min=_parse_float(low, f"range {number}, from"),
            max=_parse_float(high, f"range {number}, to"),
        )


class App(ctk.CTk):
    def __init__(self, config_path: Path, autostart: bool = False) -> None:
        super().__init__()
        self.title("CSV FTPS Uploader")
        self.geometry("1000x800")
        self.minsize(820, 620)
        self._set_icon()

        self.config_path = config_path
        self.events: queue.Queue[tuple[str, ...]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.scheduled = False
        self.range_rows: list[RangeRow] = []
        self.saved_password: str | None = None
        self.last_run = ""

        self.log_handler = QueueHandler(self.events)
        log.addHandler(self.log_handler)
        log.setLevel(logging.INFO)
        log.propagate = False  # a windowed .exe has no console to print to

        self._build_header()
        self._build_footer()
        self._build_tabs()
        self._build_log()

        self.config_data = self._load_config()
        self._fill_form(self.config_data)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)
        if autostart:
            self.after(500, self.toggle_schedule)

    # ----------------------------------------------------------------- setup

    def _set_icon(self) -> None:
        icon = ASSETS / "icon.ico"
        if sys.platform == "win32" and icon.exists():
            # CustomTkinter sets its own icon ~200 ms after start; ours must come later.
            self.after(300, lambda: self.iconbitmap(str(icon)))

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 4))

        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="CSV FTPS Uploader", font=ctk.CTkFont(size=22, weight="bold")).pack(
            anchor="w"
        )
        ctk.CTkLabel(
            titles,
            text="Converts a CSV or Excel file with your rules and uploads it to an FTPS server on schedule.",
            text_color=MUTED,
        ).pack(anchor="w")

        self.theme_menu = ctk.CTkOptionMenu(
            header, values=["System", "Light", "Dark"], width=110, command=self._theme
        )
        self.theme_menu.set("System")
        self.theme_menu.pack(side="right")

    def _build_tabs(self) -> None:
        self.tabs = ctk.CTkTabview(self, height=370)
        self.tabs.pack(fill="x", padx=20, pady=(0, 4))
        self._build_files_tab(self.tabs.add("Files"))
        self._build_rules_tab(self.tabs.add("Conversion"))
        self._build_server_tab(self.tabs.add("Server"))

    def _build_files_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(1, weight=1)
        self.input_entry = self._path_row(tab, 0, "Input file", self._pick_input)
        self.output_entry = self._path_row(tab, 1, "Converted file", self._pick_output)
        _hint(tab, "CSV or Excel (.xlsx). Written on every run, then uploaded with the files below.").grid(
            row=2, column=1, sticky="w", pady=(0, 8)
        )

        ctk.CTkLabel(tab, text="Also upload").grid(row=3, column=0, sticky="nw", padx=(0, 12), pady=4)
        self.extra_box = ctk.CTkTextbox(tab, height=110, font=ctk.CTkFont(family="Consolas", size=12))
        self.extra_box.grid(row=3, column=1, sticky="nsew", pady=4)
        tab.grid_rowconfigure(3, weight=1)
        ctk.CTkButton(tab, text="Add files…", width=110, command=self._pick_extra).grid(
            row=3, column=2, sticky="n", padx=(8, 0), pady=4
        )
        _hint(tab, "One file per line. They are uploaded as they are, without conversion.").grid(
            row=4, column=1, sticky="w"
        )

    def _path_row(self, tab: ctk.CTkFrame, row: int, text: str, command) -> ctk.CTkEntry:
        ctk.CTkLabel(tab, text=text).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
        entry = ctk.CTkEntry(tab)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        ctk.CTkButton(tab, text="Browse…", width=110, command=command).grid(
            row=row, column=2, padx=(8, 0), pady=4
        )
        return entry

    def _build_rules_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(1, weight=1)
        left = ctk.CTkFrame(tab, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nw", padx=(0, 24))

        self.delimiter_entry = _field(left, 0, "CSV delimiter", width=50)
        self.in_encoding = _combo(left, 1, "CSV input encoding", ENCODINGS)
        self.out_encoding = _combo(left, 2, "CSV output encoding", ENCODINGS)
        self.sheet_entry = _field(left, 3, "Excel sheet", width=150, placeholder="first sheet")
        self.column_entry = _field(left, 4, "Column to convert", width=150)
        _hint(left, "Number from 0, or the column name").grid(row=5, column=1, sticky="w")
        self.header_column_entry = _field(left, 6, "Header marker column", width=50)
        self.header_markers_entry = _field(left, 7, "Header markers", width=150)
        _hint(left, "Comma-separated. The first row is\nalways a header.").grid(row=8, column=1, sticky="w")
        self.empty_values_entry = _field(left, 9, "Treat as empty", width=150)
        self.empty_label_entry = _field(left, 10, "Empty becomes", width=150)

        right = ctk.CTkFrame(tab, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        tab.grid_rowconfigure(0, weight=1)
        top = ctk.CTkFrame(right, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text="Ranges", font=ctk.CTkFont(weight="bold")).pack(side="left")
        _hint(top, "  from ≤ value < to · first match wins").pack(side="left")
        ctk.CTkButton(top, text="Reset", width=70, command=self._reset_ranges, **_SECONDARY).pack(
            side="right"
        )
        ctk.CTkButton(top, text="Add range", width=100, command=lambda: self._add_range(Range(""))).pack(
            side="right", padx=6
        )

        self.ranges_frame = ctk.CTkScrollableFrame(right, height=230)
        self.ranges_frame.pack(fill="both", expand=True, pady=(6, 0))
        self.ranges_frame.grid_columnconfigure(2, weight=1)
        for column, text in enumerate(("From", "To", "Becomes")):
            ctk.CTkLabel(self.ranges_frame, text=text, text_color=MUTED).grid(
                row=0, column=column, sticky="w"
            )

    def _build_server_tab(self, tab: ctk.CTkFrame) -> None:
        self.host_entry = _field(tab, 0, "Host", width=300)
        self.port_entry = _field(tab, 1, "Port", width=70)
        self.user_entry = _field(tab, 2, "User", width=300)
        self.password_entry = _field(tab, 3, "Password", width=300)
        self.password_entry.configure(show="•")
        self.remember = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(tab, text="Remember password", variable=self.remember).grid(
            row=3, column=2, sticky="w", padx=12
        )
        self.remote_dir_entry = _field(tab, 4, "Remote folder", width=300)
        _hint(tab, "Leave empty for the folder you land in after login.").grid(row=5, column=1, sticky="w")
        self.verify = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(tab, text="Verify the server certificate", variable=self.verify).grid(
            row=6, column=1, sticky="w", pady=(8, 2)
        )
        _hint(tab, "Turn off only for a server with a self-signed certificate you trust.").grid(
            row=7, column=1, sticky="w"
        )
        self.test_button = ctk.CTkButton(tab, text="Test connection", width=150, command=self.test)
        self.test_button.grid(row=8, column=1, sticky="w", pady=(14, 0))
        _hint(tab, "The password is kept in the system keyring (Windows Credential Manager).").grid(
            row=9, column=1, columnspan=2, sticky="w", pady=(10, 0)
        )

    def _build_log(self) -> None:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=(4, 0))
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text="Log", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(top, text="Clear", width=70, command=self._clear_log, **_SECONDARY).pack(side="right")
        ctk.CTkButton(
            top, text="Open settings folder", width=150, command=self._open_settings_folder, **_SECONDARY
        ).pack(side="right", padx=6)

        self.log_box = ctk.CTkTextbox(frame, font=ctk.CTkFont(family="Consolas", size=12), wrap="word")
        self.log_box.pack(fill="both", expand=True, pady=(4, 0))
        self.log_box.configure(state="disabled")
        for level, (light, dark) in LOG_COLORS.items():
            self.log_box.tag_config(level, foreground=light if ctk.get_appearance_mode() == "Light" else dark)

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=20, pady=(10, 16))

        self.status_dot = ctk.CTkLabel(footer, text="●", text_color=MUTED, width=16)
        self.status_dot.pack(side="left")
        self.status = ctk.CTkLabel(footer, text=f"Idle · v{__version__}", text_color=MUTED)
        self.status.pack(side="left", padx=(4, 0))

        self.start_button = ctk.CTkButton(
            footer, text="Start", width=110, font=ctk.CTkFont(weight="bold"), command=self.toggle_schedule
        )
        self.start_button.pack(side="right")
        self.once_button = ctk.CTkButton(footer, text="Run once", width=100, command=self.run_now)
        self.once_button.pack(side="right", padx=8)
        self.convert_button = ctk.CTkButton(
            footer, text="Convert only", width=110, command=self.convert_only, **_SECONDARY
        )
        self.convert_button.pack(side="right")

        ctk.CTkLabel(footer, text="min", text_color=MUTED).pack(side="right", padx=(4, 20))
        self.interval_entry = ctk.CTkEntry(footer, width=56, justify="right")
        self.interval_entry.pack(side="right")
        ctk.CTkLabel(footer, text="Every", text_color=MUTED).pack(side="right", padx=(0, 6))

    # --------------------------------------------------------- settings <-> form

    def _load_config(self) -> Config:
        if not self.config_path.exists():
            log.info("No settings yet; they will be saved to %s", self.config_path)
            return Config(input="", output="", base_dir=self.config_path.parent)
        try:
            config = settings.load(self.config_path)
        except (ConfigError, OSError) as exc:
            log.error("Could not read the settings, starting with defaults: %s", exc)
            return Config(input="", output="", base_dir=self.config_path.parent)
        log.info("Settings loaded from %s", self.config_path)
        return config

    def _fill_form(self, config: Config) -> None:
        rules, server = config.rules, config.server
        _set(self.input_entry, config.input)
        _set(self.output_entry, config.output)
        self.extra_box.delete("1.0", "end")
        self.extra_box.insert("1.0", "\n".join(config.extra_files))

        _set(self.delimiter_entry, rules.delimiter)
        self.in_encoding.set(rules.input_encoding)
        self.out_encoding.set(rules.output_encoding)
        _set(self.sheet_entry, str(rules.sheet))
        _set(self.column_entry, str(rules.column))
        _set(self.header_column_entry, str(rules.header_column))
        _set(self.header_markers_entry, ", ".join(rules.header_markers))
        _set(self.empty_values_entry, ", ".join(v for v in rules.empty_values if v))
        _set(self.empty_label_entry, rules.empty_label)
        self._set_ranges(rules.ranges)

        _set(self.host_entry, server.host)
        _set(self.port_entry, str(server.port))
        _set(self.user_entry, server.user)
        _set(self.remote_dir_entry, server.remote_dir)
        self.verify.set(server.verify_certificate)
        self.saved_password = get_password(server) if server.host and server.user else None
        _set(self.password_entry, self.saved_password or "")
        self.remember.set(True)

        _set(self.interval_entry, _number_text(config.interval / 60))

    def _read_form(self) -> Config:
        """Build settings from the form; raise ConfigError with a readable message."""
        config = Config(
            input=self.input_entry.get().strip(),
            output=self.output_entry.get().strip(),
            extra_files=[
                line.strip() for line in self.extra_box.get("1.0", "end").splitlines() if line.strip()
            ],
            base_dir=self.config_data.base_dir,
        )
        # Keep settings that have no field in the window, like timeouts and retries.
        config.server = settings.Server(**vars(self.config_data.server))
        if not config.input or not config.output:
            raise ConfigError("choose the input file and where to save the converted file (Files tab)")

        rules = config.rules
        rules.delimiter = self.delimiter_entry.get()
        rules.input_encoding = self.in_encoding.get().strip()
        rules.output_encoding = self.out_encoding.get().strip()
        sheet = self.sheet_entry.get().strip()
        rules.sheet = int(sheet) if sheet.isdigit() else sheet
        column = self.column_entry.get().strip()
        rules.column = int(column) if column.isdigit() else column
        rules.header_column = _parse_int(self.header_column_entry.get(), "header marker column")
        rules.header_markers = _split(self.header_markers_entry.get())
        rules.empty_values = ["", *_split(self.empty_values_entry.get())]  # blank cells always count
        rules.empty_label = self.empty_label_entry.get()
        rules.ranges = [r for n, row in enumerate(self.range_rows, 1) if (r := row.read(n)) is not None]

        server = config.server
        server.host = self.host_entry.get().strip()
        server.port = _parse_int(self.port_entry.get(), "port")
        server.user = self.user_entry.get().strip()
        server.remote_dir = self.remote_dir_entry.get().strip()
        server.verify_certificate = self.verify.get()

        minutes = _parse_float(self.interval_entry.get(), "interval")
        if minutes is None:
            raise ConfigError("interval: enter the minutes between runs")
        config.interval = max(1, round(minutes * 60))
        settings.validate(config)
        return config

    def _save(self) -> Config | None:
        """Read, check and save the form. Show the problem and return None if it is invalid."""
        try:
            config = self._read_form()
            settings.save(config, self.config_path)
        except ConfigError as exc:
            self._show_error("Check the settings", str(exc))
            return None
        except OSError as exc:
            self._show_error("Could not save the settings", str(exc))
            return None
        self.config_data = config
        self._save_password(config)
        return config

    def _save_password(self, config: Config) -> None:
        password = self.password_entry.get()
        server = config.server
        try:
            if self.remember.get() and password and password != get_password(server):
                set_password(server, password)
                log.info("Password saved in the system keyring")
            elif not self.remember.get() and self.saved_password is not None:
                delete_password(server)
                log.info("Saved password removed from the system keyring")
        except CredentialsError as exc:
            log.warning("%s", exc)
        self.saved_password = password if self.remember.get() else None

    def _password(self, config: Config) -> str | None:
        return self.password_entry.get() or get_password(config.server)

    # ---------------------------------------------------------------- ranges

    def _set_ranges(self, ranges: Sequence[Range]) -> None:
        for row in self.range_rows:
            row.destroy()
        self.range_rows = []
        for item in ranges:
            self._add_range(item)

    def _add_range(self, item: Range) -> None:
        self.range_rows.append(
            RangeRow(self.ranges_frame, len(self.range_rows) + 1, item, self._remove_range)
        )

    def _remove_range(self, row: RangeRow) -> None:
        row.destroy()
        self.range_rows.remove(row)
        for number, other in enumerate(self.range_rows, 1):
            other.place(number)

    def _reset_ranges(self) -> None:
        if messagebox.askyesno(
            "Reset ranges?", "Replace the ranges with the default size groups?", parent=self
        ):
            self._set_ranges(settings.default_ranges())

    # --------------------------------------------------------------- actions

    def convert_only(self) -> None:
        if config := self._save():
            self._start_worker(lambda: run_once(config, do_upload=False), "Converting…")

    def run_now(self) -> None:
        if (config := self._save()) and (password := self._require_password(config)):
            self._start_worker(lambda: run_once(config, password, stop=self.stop_event), "Uploading…")

    def test(self) -> None:
        if (config := self._save()) and (password := self._require_password(config)):

            def job() -> None:
                folder = test_connection(config.server, password)
                log.info("Connection OK: logged in to %s, remote folder %s", config.server.host, folder)

            self._start_worker(job, "Connecting…")

    def toggle_schedule(self) -> None:
        if self.scheduled:
            self.stop_event.set()
            self.start_button.configure(state="disabled", text="Stopping…")
            self._set_status("Stopping after the current step…", "busy")
            return
        if not (config := self._save()) or not (password := self._require_password(config)):
            return

        def job() -> None:
            log.info("Schedule started: every %s min", _number_text(config.interval / 60))
            run_forever(
                config,
                password,
                stop=self.stop_event,
                on_run=lambda result, error: self.events.put(("run", _run_text(result, error))),
                on_wait=lambda when: self.events.put(("wait", when.strftime("%H:%M:%S"))),
            )
            log.info("Schedule stopped")

        self.scheduled = True
        self._start_worker(job, "Running…")
        self.start_button.configure(state="normal", text="Stop", fg_color=("#cf222e", "#b62324"))

    def _require_password(self, config: Config) -> str | None:
        password = self._password(config)
        if not password:
            self.tabs.set("Server")
            self.password_entry.focus_set()
            self._show_error("Password needed", "Enter the FTPS password on the Server tab.")
        return password

    def _start_worker(self, job, status: str) -> None:
        self.stop_event.clear()
        self._set_busy(True)
        self._set_status(status, "busy")

        def target() -> None:
            try:
                job()
            except (RunError, UploadError) as exc:
                log.error("%s", exc)
                self.events.put(("finished", "error", str(exc)))
            except Exception as exc:  # keep the window alive and show what went wrong
                log.exception("Unexpected error")
                self.events.put(("finished", "error", f"unexpected error: {exc}"))
            else:
                self.events.put(("finished", "ok", ""))

        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def _poll(self) -> None:
        """Apply messages from the worker thread; Tk may only be touched here."""
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "log":
                self._append_log(event[1], event[2])
            elif kind == "run":
                self.last_run = event[1]
            elif kind == "wait":
                self._set_status(f"{self.last_run} · next run at {event[1]}", "ok")
            elif kind == "finished":
                self._finished(event[1], event[2])
        self.after(100, self._poll)

    def _finished(self, outcome: str, error: str) -> None:
        was_scheduled = self.scheduled
        self.scheduled = False
        self._set_busy(False)
        self.start_button.configure(text="Start", fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])
        if outcome == "error":
            self._set_status(f"Failed: {error}", "error")
        elif was_scheduled:
            self._set_status(f"Stopped · v{__version__}", "idle")
        else:
            self._set_status(f"Done at {datetime.now():%H:%M:%S}", "ok")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in (self.once_button, self.convert_button, self.test_button):
            button.configure(state=state)
        self.start_button.configure(state="normal" if not busy or self.scheduled else "disabled")

    # ------------------------------------------------------------ file pickers

    def _pick_input(self) -> None:
        if path := filedialog.askopenfilename(parent=self, title="Choose the input file", filetypes=_INPUT):
            _set(self.input_entry, path)
            if not self.output_entry.get().strip():
                # Same format as the input; a macro workbook cannot be written, so make it .xlsx.
                source = Path(path)
                suffix = ".xlsx" if source.suffix.lower() == ".xlsm" else source.suffix
                _set(self.output_entry, str(source.with_name(f"{source.stem}_converted{suffix}")))

    def _pick_output(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self, title="Save the converted file as", defaultextension=".csv", filetypes=_OUTPUT
        )
        if path:
            _set(self.output_entry, path)

    def _pick_extra(self) -> None:
        paths = filedialog.askopenfilenames(parent=self, title="Files to upload as they are")
        if paths:
            current = self.extra_box.get("1.0", "end").strip()
            self.extra_box.delete("1.0", "end")
            self.extra_box.insert("1.0", "\n".join(filter(None, [current, *paths])))

    # ------------------------------------------------------------------- misc

    def _theme(self, mode: str) -> None:
        ctk.set_appearance_mode(mode)
        for level, (light, dark) in LOG_COLORS.items():
            self.log_box.tag_config(level, foreground=light if ctk.get_appearance_mode() == "Light" else dark)

    def _append_log(self, level: str, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", level if level in LOG_COLORS else ())
        lines = int(self.log_box.index("end-1c").split(".")[0])
        if lines > MAX_LOG_LINES:
            self.log_box.delete("1.0", f"{lines - MAX_LOG_LINES}.0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _open_settings_folder(self) -> None:
        folder = self.config_path.parent
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(folder)], check=False)

    def _set_status(self, text: str, state: str = "idle") -> None:
        colors = {"idle": MUTED, "busy": ("#9a6700", "#d29922"), "ok": ("#1a7f37", "#3fb950")}
        colors["error"] = LOG_COLORS["ERROR"]
        self.status_dot.configure(text_color=colors[state])
        self.status.configure(text=text if len(text) < 110 else text[:107] + "…")

    def _show_error(self, title: str, text: str) -> None:
        self._set_status(text, "error")
        messagebox.showerror(title, text, parent=self)

    def _on_close(self) -> None:
        if self.scheduled and not messagebox.askyesno(
            "Stop and quit?", "The schedule is running. Stop it and close the app?", parent=self
        ):
            return
        self.stop_event.set()
        try:
            config = self._read_form()
            settings.save(config, self.config_path)
            self._save_password(config)
        except (ConfigError, OSError):
            pass  # unfinished settings are not worth blocking the exit for
        log.removeHandler(self.log_handler)
        self.destroy()


# ---------------------------------------------------------------- helpers

_INPUT = [
    ("CSV or Excel", "*.csv *.txt *.xlsx *.xlsm"),
    ("CSV files", "*.csv *.txt"),
    ("Excel workbooks", "*.xlsx *.xlsm"),
    ("All files", "*.*"),
]
_OUTPUT = [("CSV file", "*.csv"), ("Excel workbook", "*.xlsx"), ("All files", "*.*")]
_SECONDARY = {"fg_color": "transparent", "border_width": 1, "text_color": ("gray10", "gray90")}


def _field(
    parent: ctk.CTkFrame, row: int, text: str, width: int, placeholder: str | None = None
) -> ctk.CTkEntry:
    ctk.CTkLabel(parent, text=text).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
    entry = ctk.CTkEntry(parent, width=width, placeholder_text=placeholder)
    entry.grid(row=row, column=1, sticky="w", pady=4)
    return entry


def _combo(parent: ctk.CTkFrame, row: int, text: str, values: list[str]) -> ctk.CTkComboBox:
    ctk.CTkLabel(parent, text=text).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
    combo = ctk.CTkComboBox(parent, values=values, width=150)
    combo.grid(row=row, column=1, sticky="w", pady=4)
    return combo


def _hint(parent: ctk.CTkFrame, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, text_color=MUTED, font=ctk.CTkFont(size=12), justify="left")


def _set(entry: ctk.CTkEntry, value: str) -> None:
    # Leave an empty entry alone: deleting or inserting "" would hide its placeholder text.
    if entry.get():
        entry.delete(0, "end")
    if value:
        entry.insert(0, value)


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _parse_int(text: str, name: str) -> int:
    try:
        return int(text.strip())
    except ValueError:
        raise ConfigError(f"{name}: enter a whole number") from None


def _parse_float(text: str, name: str) -> float | None:
    text = text.strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise ConfigError(f"{name}: enter a number") from None


def _number_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _run_text(result: RunResult | None, error: str | None) -> str:
    stamp = datetime.now().strftime("%H:%M")
    if error:
        return f"Last run {stamp} failed"
    if result and not result.complete:
        return f"Last run {stamp}: some files missing"
    return f"Last run {stamp} OK"


def main(argv: Sequence[str] | None = None) -> None:
    """Start the app. ``--start`` begins the schedule right away; a path picks the settings file."""
    if sys.platform == "win32":
        # Show our own icon in the taskbar instead of the generic Python one.
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SilentCasting.CsvFtps")
        except (AttributeError, OSError):
            pass
    args = list(sys.argv[1:] if argv is None else argv)
    autostart = "--start" in args
    paths = [a for a in args if a != "--start"]
    config_path = Path(paths[0]).resolve() if paths else settings.default_config_path()
    ctk.set_appearance_mode("System")
    App(config_path, autostart=autostart).mainloop()


if __name__ == "__main__":
    main()
