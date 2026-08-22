from __future__ import annotations

import sys
import tkinter as tk
from concurrent.futures import Future
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from .backend import ConsoleBackend
from .models import BackfillPlanView, DashboardSnapshot, TablePage
from .tasks import SerialTaskRunner


PAGE_SIZES = (50, 100, 250, 500, 1000)


class TableView(ttk.Frame):
    def __init__(self, parent, *, paged: bool = False):
        super().__init__(parent)
        self.current_page = TablePage((), ())
        self._previous: Callable[[], None] | None = None
        self._next: Callable[[], None] | None = None

        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table_frame, show="headings", selectmode="browse")
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        footer = ttk.Frame(self)
        footer.pack(fill="x", pady=(6, 0))
        self.info = ttk.Label(footer, text="No data loaded")
        self.info.pack(side="left")
        self.next_button = ttk.Button(footer, text="Next", state="disabled", command=self._go_next)
        self.previous_button = ttk.Button(
            footer, text="Previous", state="disabled", command=self._go_previous
        )
        if paged:
            self.next_button.pack(side="right")
            self.previous_button.pack(side="right", padx=(0, 6))

    def set_page(
        self,
        page: TablePage,
        *,
        previous: Callable[[], None] | None = None,
        next_: Callable[[], None] | None = None,
    ) -> None:
        self.current_page = page
        self._previous = previous
        self._next = next_
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = page.columns
        for column in page.columns:
            self.tree.heading(column, text=column)
            width = min(280, max(95, len(column) * 9 + 24))
            self.tree.column(column, width=width, minwidth=70, stretch=True)
        for row in page.rows:
            self.tree.insert("", "end", values=row)
        start = (page.page - 1) * page.page_size + 1 if page.total_rows else 0
        end = min(page.page * page.page_size, page.total_rows)
        self.info.configure(
            text=f"Rows {start:,}-{end:,} of {page.total_rows:,} | Page {page.page} of {page.total_pages}"
        )
        self.previous_button.configure(
            state="normal" if page.has_previous and previous is not None else "disabled"
        )
        self.next_button.configure(state="normal" if page.has_next and next_ is not None else "disabled")

    def _go_previous(self) -> None:
        if self._previous is not None:
            self._previous()

    def _go_next(self) -> None:
        if self._next is not None:
            self._next()


class ConsoleApp:
    def __init__(self, root: tk.Tk, backend: ConsoleBackend, settings_path: str):
        self.root = root
        self.backend = backend
        self.settings_path = str(Path(settings_path).resolve())
        self.tasks = SerialTaskRunner()
        self._busy = False

        root.title("MarketVault Console")
        root.geometry("1480x900")
        root.minsize(1120, 720)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._configure_style()

        self.status_text = tk.StringVar(value="Ready | Local operations only")
        self.error_text = tk.StringVar(value="")
        self._build_header()
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self._build_dashboard()
        self._build_explorer()
        self._build_inventory()
        self._build_coverage_audit()
        self._build_intraday_audit()
        self._build_calendar()
        self._build_backfill()
        self._build_runs()
        self._build_status_bar()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        available = style.theme_names()
        if "vista" in available:
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Metric.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Muted.TLabel", foreground="#5b6470")
        style.configure("Error.TLabel", foreground="#a4262c")
        style.configure("Network.TButton", foreground="#8a3b00")
        style.configure("Treeview", rowheight=25, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(header, text="MarketVault Console", style="Title.TLabel").pack(side="left")
        context = ttk.Frame(header)
        context.pack(side="right")
        ttk.Label(context, text="LOCAL MODE", foreground="#107c10").pack(anchor="e")
        ttk.Label(
            context,
            text=f"Settings: {self.settings_path} | OpenD only on explicit Fetch or Execute",
            style="Muted.TLabel",
        ).pack(anchor="e")

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(14, 6))
        bar.pack(fill="x", side="bottom")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.progress.pack(side="right")
        ttk.Label(bar, textvariable=self.status_text).pack(side="left")
        ttk.Label(bar, textvariable=self.error_text, style="Error.TLabel").pack(side="left", padx=16)

    def _new_tab(self, title: str) -> ttk.Frame:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text=title)
        return tab

    def _build_dashboard(self) -> None:
        tab = self._new_tab("Dashboard")
        top = ttk.Frame(tab)
        top.pack(fill="x")
        ttk.Label(top, text="Local archive overview", font=("Segoe UI", 12, "bold")).pack(side="left")
        ttk.Button(top, text="Refresh", command=self._refresh_dashboard).pack(side="right")
        self.dashboard_metrics = ttk.Frame(tab)
        self.dashboard_metrics.pack(fill="x", pady=12)
        self.metric_values: dict[str, tk.StringVar] = {}
        for index, name in enumerate(
            ("Symbols", "Snapshots", "Latest rows", "Completed dates", "Incomplete dates", "Latest trade date")
        ):
            panel = ttk.LabelFrame(self.dashboard_metrics, text=name, padding=10)
            panel.grid(row=0, column=index, padx=(0, 8), sticky="nsew")
            value = tk.StringVar(value="-")
            self.metric_values[name] = value
            ttk.Label(panel, textvariable=value, style="Metric.TLabel").pack()
            self.dashboard_metrics.columnconfigure(index, weight=1)
        ttk.Label(tab, text="Recent runs", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 6))
        self.dashboard_runs = TableView(tab)
        self.dashboard_runs.pack(fill="both", expand=True)

    def _build_explorer(self) -> None:
        tab = self._new_tab("Data Explorer")
        form = ttk.LabelFrame(tab, text="Bounded local market-bar query", padding=10)
        form.pack(fill="x")
        self.explorer_vars = {
            "code": tk.StringVar(value="US.SPY"),
            "start_date": tk.StringVar(),
            "end_date": tk.StringVar(),
            "interval": tk.StringVar(value="1m"),
            "requested_session": tk.StringVar(value="ALL"),
            "bar_session": tk.StringVar(),
            "adjustment": tk.StringVar(value="NONE"),
            "page_size": tk.IntVar(value=100),
        }
        self._entry(form, "Code", self.explorer_vars["code"], 0)
        self._entry(form, "Start date", self.explorer_vars["start_date"], 1)
        self._entry(form, "End date", self.explorer_vars["end_date"], 2)
        self._combo(form, "Interval", self.explorer_vars["interval"], ("1m", "5m", "15m", "30m", "60m", "day"), 3)
        self._combo(form, "Request session", self.explorer_vars["requested_session"], ("", "ALL", "RTH", "ETH"), 4)
        self._combo(form, "Bar session", self.explorer_vars["bar_session"], ("", "OVERNIGHT", "PRE_MARKET", "REGULAR", "AFTER_HOURS"), 5)
        self._combo(form, "Adjustment", self.explorer_vars["adjustment"], ("NONE", "QFQ", "HFQ"), 6)
        self._combo(form, "Rows/page", self.explorer_vars["page_size"], PAGE_SIZES, 7)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Query", command=lambda: self._query_explorer(1)).pack(side="left")
        ttk.Button(actions, text="Export page CSV", command=lambda: self._export(self.explorer_table, "csv")).pack(side="left", padx=6)
        ttk.Button(actions, text="Export page JSON", command=lambda: self._export(self.explorer_table, "json")).pack(side="left")
        self.explorer_table = TableView(tab, paged=True)
        self.explorer_table.pack(fill="both", expand=True)

    def _build_inventory(self) -> None:
        tab = self._new_tab("Inventory")
        form = ttk.LabelFrame(tab, text="Local physical and logical inventory", padding=10)
        form.pack(fill="x")
        self.inventory_vars = {
            "symbols": tk.StringVar(),
            "start_date": tk.StringVar(),
            "end_date": tk.StringVar(),
            "interval": tk.StringVar(),
            "session": tk.StringVar(),
            "adjustment": tk.StringVar(),
        }
        for index, key in enumerate(self.inventory_vars):
            self._entry(form, key.replace("_", " ").title(), self.inventory_vars[key], index)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Run inventory", command=self._run_inventory).pack(side="left")
        ttk.Button(actions, text="Export page CSV", command=lambda: self._export(self.inventory_table, "csv")).pack(side="left", padx=6)
        self.inventory_summary = tk.StringVar(value="No inventory run")
        ttk.Label(actions, textvariable=self.inventory_summary, style="Muted.TLabel").pack(side="left", padx=14)
        self.inventory_table = TableView(tab)
        self.inventory_table.pack(fill="both", expand=True)

    def _build_coverage_audit(self) -> None:
        tab = self._new_tab("Coverage Audit")
        self.coverage_vars = self._audit_form(tab, "Trading-date coverage audit")
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Run coverage audit", command=self._run_coverage).pack(side="left")
        ttk.Button(actions, text="Export page CSV", command=lambda: self._export(self.coverage_table, "csv")).pack(side="left", padx=6)
        self.coverage_summary = tk.StringVar(value="No audit run")
        ttk.Label(actions, textvariable=self.coverage_summary, style="Muted.TLabel").pack(side="left", padx=14)
        self.coverage_table = TableView(tab)
        self.coverage_table.pack(fill="both", expand=True)

    def _build_intraday_audit(self) -> None:
        tab = self._new_tab("Intraday Audit")
        self.intraday_vars = self._audit_form(tab, "Latest complete snapshot structure")
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Run intraday audit", command=self._run_intraday).pack(side="left")
        ttk.Button(actions, text="Export page CSV", command=lambda: self._export(self.intraday_table, "csv")).pack(side="left", padx=6)
        self.intraday_summary = tk.StringVar(value="No audit run")
        ttk.Label(actions, textvariable=self.intraday_summary, style="Muted.TLabel").pack(side="left", padx=14)
        self.intraday_table = TableView(tab)
        self.intraday_table.pack(fill="both", expand=True)

    def _audit_form(self, tab: ttk.Frame, title: str) -> dict[str, tk.StringVar]:
        form = ttk.LabelFrame(tab, text=title, padding=10)
        form.pack(fill="x")
        values = {
            "symbols": tk.StringVar(value="US.SPY"),
            "start_date": tk.StringVar(),
            "end_date": tk.StringVar(),
            "calendar_market": tk.StringVar(value="US"),
            "calendar_code": tk.StringVar(),
            "interval": tk.StringVar(value="1m"),
            "session": tk.StringVar(value="ALL"),
            "adjustment": tk.StringVar(value="NONE"),
        }
        for index, key in enumerate(values):
            self._entry(form, key.replace("_", " ").title(), values[key], index)
        return values

    def _build_calendar(self) -> None:
        tab = self._new_tab("Trading Calendar")
        form = ttk.LabelFrame(tab, text="Local query and explicit OpenD fetch", padding=10)
        form.pack(fill="x")
        self.calendar_vars = {
            "scope": tk.StringVar(value="MARKET"),
            "market": tk.StringVar(value="US"),
            "code": tk.StringVar(),
            "start_date": tk.StringVar(),
            "end_date": tk.StringVar(),
            "page_size": tk.IntVar(value=100),
        }
        self._combo(form, "Scope", self.calendar_vars["scope"], ("MARKET", "CODE"), 0)
        self._entry(form, "Market", self.calendar_vars["market"], 1)
        self._entry(form, "Code", self.calendar_vars["code"], 2)
        self._entry(form, "Start date", self.calendar_vars["start_date"], 3)
        self._entry(form, "End date", self.calendar_vars["end_date"], 4)
        self._combo(form, "Rows/page", self.calendar_vars["page_size"], PAGE_SIZES, 5)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Query local", command=lambda: self._query_calendar(1)).pack(side="left")
        ttk.Button(
            actions,
            text="Fetch from OpenD",
            style="Network.TButton",
            command=self._collect_calendar,
        ).pack(side="left", padx=6)
        ttk.Button(actions, text="Export page CSV", command=lambda: self._export(self.calendar_table, "csv")).pack(side="left")
        self.calendar_table = TableView(tab, paged=True)
        self.calendar_table.pack(fill="both", expand=True)

    def _build_backfill(self) -> None:
        tab = self._new_tab("Backfill")
        form = ttk.LabelFrame(tab, text="Calendar-driven historical backfill", padding=10)
        form.pack(fill="x")
        self.backfill_vars: dict[str, Any] = {
            "symbols": tk.StringVar(value="US.SPY"),
            "start_date": tk.StringVar(),
            "end_date": tk.StringVar(),
            "bootstrap_start_date": tk.StringVar(),
            "calendar_market": tk.StringVar(value="US"),
            "calendar_code": tk.StringVar(),
            "interval": tk.StringVar(value="1m"),
            "session": tk.StringVar(value="ALL"),
            "adjustment": tk.StringVar(value="NONE"),
            "max_retries": tk.IntVar(value=2),
            "retry_backoff_seconds": tk.DoubleVar(value=2.0),
            "force": tk.BooleanVar(value=False),
            "incremental": tk.BooleanVar(value=False),
        }
        fields = [key for key in self.backfill_vars if key not in {"force", "incremental"}]
        for index, key in enumerate(fields):
            self._entry(form, key.replace("_", " ").title(), self.backfill_vars[key], index)
        flags = ttk.Frame(form)
        flags.grid(row=2, column=0, columnspan=8, sticky="w", pady=(8, 0))
        ttk.Checkbutton(flags, text="Incremental", variable=self.backfill_vars["incremental"]).pack(side="left")
        ttk.Checkbutton(flags, text="Force re-collection", variable=self.backfill_vars["force"]).pack(side="left", padx=12)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Plan locally", command=self._plan_backfill).pack(side="left")
        ttk.Button(
            actions,
            text="Execute via OpenD",
            style="Network.TButton",
            command=self._execute_backfill,
        ).pack(side="left", padx=6)
        self.backfill_summary = tk.StringVar(value="No plan generated")
        ttk.Label(actions, textvariable=self.backfill_summary, style="Muted.TLabel").pack(side="left", padx=14)
        self.backfill_table = TableView(tab)
        self.backfill_table.pack(fill="both", expand=True)

    def _build_runs(self) -> None:
        tab = self._new_tab("Runs")
        form = ttk.LabelFrame(tab, text="Local collection and dataset run history", padding=10)
        form.pack(fill="x")
        self.runs_vars = {
            "status": tk.StringVar(),
            "dataset": tk.StringVar(),
            "page_size": tk.IntVar(value=100),
        }
        self._combo(form, "Status", self.runs_vars["status"], ("", "RUNNING", "SUCCESS", "PARTIAL", "FAILED"), 0)
        self._entry(form, "Dataset", self.runs_vars["dataset"], 1)
        self._combo(form, "Rows/page", self.runs_vars["page_size"], PAGE_SIZES, 2)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="Refresh", command=lambda: self._query_runs(1)).pack(side="left")
        ttk.Button(actions, text="Export page CSV", command=lambda: self._export(self.runs_table, "csv")).pack(side="left", padx=6)
        self.runs_table = TableView(tab, paged=True)
        self.runs_table.pack(fill="both", expand=True)

    def _entry(self, parent, label: str, variable: tk.Variable, column: int) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=0 if column < 8 else 1, column=column % 8, padx=(0, 8), sticky="ew")
        ttk.Label(frame, text=label).pack(anchor="w")
        ttk.Entry(frame, textvariable=variable, width=17).pack(fill="x")
        parent.columnconfigure(column % 8, weight=1)

    def _combo(self, parent, label: str, variable: tk.Variable, values, column: int) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=0 if column < 8 else 1, column=column % 8, padx=(0, 8), sticky="ew")
        ttk.Label(frame, text=label).pack(anchor="w")
        ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", width=15).pack(fill="x")
        parent.columnconfigure(column % 8, weight=1)

    def _submit(
        self,
        name: str,
        operation: Callable[[], Any],
        success: Callable[[Any], None],
        *,
        requires_opend: bool = False,
    ) -> None:
        if self._busy:
            messagebox.showinfo("Operation running", "Wait for the current operation to finish.")
            return
        if requires_opend:
            settings = self.backend.vault.settings
            confirmed = messagebox.askyesno(
                "OpenD operation",
                f"{name} may connect to OpenD at {settings.opend_host}:{settings.opend_port}.\n\nContinue?",
            )
            if not confirmed:
                return
        self._busy = True
        self.error_text.set("")
        self.status_text.set(f"Running: {name}")
        self.progress.start(12)
        try:
            future = self.tasks.submit(name, operation)
        except Exception as exc:
            self._finish_error(name, exc)
            return
        self._poll_future(future, name, success)

    def _poll_future(self, future: Future[Any], name: str, success: Callable[[Any], None]) -> None:
        if not future.done():
            self.root.after(100, self._poll_future, future, name, success)
            return
        self._busy = False
        self.progress.stop()
        try:
            result = future.result()
            success(result)
            self.status_text.set(f"Completed: {name}")
        except Exception as exc:
            self._finish_error(name, exc)

    def _finish_error(self, name: str, exc: Exception) -> None:
        self._busy = False
        self.progress.stop()
        self.status_text.set(f"Failed: {name}")
        self.error_text.set(str(exc))
        messagebox.showerror(name, str(exc))

    def _refresh_dashboard(self) -> None:
        def success(snapshot: DashboardSnapshot) -> None:
            for name, value in snapshot.metrics.items():
                self.metric_values[name].set(value)
            self.dashboard_runs.set_page(snapshot.recent_runs)

        self._submit("Dashboard refresh", self.backend.dashboard, success)

    def _query_explorer(self, page: int) -> None:
        values = {key: variable.get() for key, variable in self.explorer_vars.items()}

        def success(result: TablePage) -> None:
            self.explorer_table.set_page(
                result,
                previous=lambda: self._query_explorer(page - 1),
                next_=lambda: self._query_explorer(page + 1),
            )

        self._submit("Market-bar query", lambda: self.backend.query_bars(page=page, **values), success)

    def _run_inventory(self) -> None:
        values = {key: variable.get() for key, variable in self.inventory_vars.items()}

        def success(result) -> None:
            summary, table = result
            self.inventory_summary.set(self._summary_text(summary))
            self.inventory_table.set_page(table)

        self._submit("Inventory", lambda: self.backend.inventory(**values), success)

    def _run_coverage(self) -> None:
        values = {key: variable.get() for key, variable in self.coverage_vars.items()}

        def success(result) -> None:
            summary, table = result
            self.coverage_summary.set(self._summary_text(summary))
            self.coverage_table.set_page(table)

        self._submit("Coverage audit", lambda: self.backend.coverage_audit(**values), success)

    def _run_intraday(self) -> None:
        values = {key: variable.get() for key, variable in self.intraday_vars.items()}

        def success(result) -> None:
            summary, table = result
            self.intraday_summary.set(self._summary_text(summary))
            self.intraday_table.set_page(table)

        self._submit("Intraday audit", lambda: self.backend.intraday_audit(**values), success)

    def _calendar_scope(self) -> tuple[str, str]:
        if self.calendar_vars["scope"].get() == "MARKET":
            return self.calendar_vars["market"].get().strip().upper(), ""
        return "", self.calendar_vars["code"].get().strip().upper()

    def _query_calendar(self, page: int) -> None:
        market, code = self._calendar_scope()
        values = {
            "market": market,
            "code": code,
            "start_date": self.calendar_vars["start_date"].get(),
            "end_date": self.calendar_vars["end_date"].get(),
            "page_size": self.calendar_vars["page_size"].get(),
        }

        def success(result: TablePage) -> None:
            self.calendar_table.set_page(
                result,
                previous=lambda: self._query_calendar(page - 1),
                next_=lambda: self._query_calendar(page + 1),
            )

        self._submit("Calendar query", lambda: self.backend.query_calendar(page=page, **values), success)

    def _collect_calendar(self) -> None:
        market, code = self._calendar_scope()
        values = {
            "market": market,
            "code": code,
            "start_date": self.calendar_vars["start_date"].get(),
            "end_date": self.calendar_vars["end_date"].get(),
        }

        def success(manifest: dict[str, Any]) -> None:
            self.status_text.set(
                f"Calendar fetch {manifest.get('status')} | run {manifest.get('run_id')} | rows {manifest.get('row_count', 0)}"
            )
            self.root.after(50, self._query_calendar, 1)

        self._submit(
            "Calendar fetch",
            lambda: self.backend.collect_calendar(**values),
            success,
            requires_opend=True,
        )

    def _backfill_values(self) -> dict[str, Any]:
        return {key: variable.get() for key, variable in self.backfill_vars.items()}

    def _plan_backfill(self) -> None:
        values = self._backfill_values()

        def success(plan: BackfillPlanView) -> None:
            self.backfill_summary.set(
                f"{plan.scope} | {plan.trading_date_count} dates | {plan.pending_count} pending | {plan.skipped_count} skipped"
            )
            self.backfill_table.set_page(plan.items)

        self._submit("Backfill plan", lambda: self.backend.plan_backfill(**values), success)

    def _execute_backfill(self) -> None:
        values = self._backfill_values()

        def success(manifest: dict[str, Any]) -> None:
            parameters = manifest.get("parameters", {})
            self.backfill_summary.set(
                f"{manifest.get('status')} | run {manifest.get('run_id')} | "
                f"success {parameters.get('successful_item_count', 0)} | failed {parameters.get('failed_item_count', 0)}"
            )

        self._submit(
            "Backfill execute",
            lambda: self.backend.execute_backfill(**values),
            success,
            requires_opend=True,
        )

    def _query_runs(self, page: int) -> None:
        values = {key: variable.get() for key, variable in self.runs_vars.items()}

        def success(result: TablePage) -> None:
            self.runs_table.set_page(
                result,
                previous=lambda: self._query_runs(page - 1),
                next_=lambda: self._query_runs(page + 1),
            )

        self._submit("Run history", lambda: self.backend.runs(page=page, **values), success)

    def _export(self, table: TableView, format_name: str) -> None:
        if not table.current_page.columns:
            messagebox.showinfo("Export", "Load a table page before exporting.")
            return
        extension = ".csv" if format_name == "csv" else ".json"
        path = filedialog.asksaveasfilename(
            defaultextension=extension,
            filetypes=[(format_name.upper(), f"*{extension}")],
        )
        if not path:
            return

        def success(result) -> None:
            messagebox.showinfo("Export complete", f"Exported {result.row_count} rows to\n{result.path}")

        self._submit(
            "Export current page",
            lambda: self.backend.export_page(table.current_page, path, format_name),
            success,
        )

    @staticmethod
    def _summary_text(summary: dict[str, Any]) -> str:
        preferred = (
            "status",
            "symbol_count",
            "snapshot_count",
            "total_expected_items",
            "complete_item_count",
            "audited_item_count",
            "warn_item_count",
            "fail_item_count",
            "coverage_percentage",
        )
        parts = [f"{key}={summary[key]}" for key in preferred if key in summary]
        if not parts:
            parts = [f"{key}={value}" for key, value in list(summary.items())[:6]]
        return " | ".join(parts)

    def _close(self) -> None:
        if self._busy:
            messagebox.showinfo("Operation running", "Wait for the current operation to finish before exiting.")
            return
        self.tasks.close()
        self.root.destroy()


def run_console(settings_path: str) -> int:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(
            "Unable to start MarketVault Console: the Python Tcl/Tk runtime is unavailable. "
            "Install or repair a standard Python distribution with Tkinter support. "
            f"Details: {exc}",
            file=sys.stderr,
        )
        return 1
    try:
        backend = ConsoleBackend.from_settings(settings_path)
    except Exception as exc:
        root.withdraw()
        messagebox.showerror("MarketVault Console", str(exc))
        root.destroy()
        return 1
    ConsoleApp(root, backend, settings_path)
    root.mainloop()
    return 0
