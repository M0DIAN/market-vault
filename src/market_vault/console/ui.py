from __future__ import annotations

import sys
import tkinter as tk
from concurrent.futures import Future
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk
from typing import Any, Callable

from ..windows_launcher import configure_window_icon
from .backend import ConsoleBackend
from .i18n import (
    LANGUAGE_NAMES,
    LOCALES_BY_NAME,
    LocalizationBindings,
    TextBinding,
    Translator,
    choose_ui_font,
)
from .models import BackfillPlanView, DashboardSnapshot, PurgePlanView, TablePage
from .preferences import UiPreferenceStore
from .shell import (
    HOME_METRICS,
    NAVIGATION_GROUPS,
    PAGE_TAB_KEYS,
    HomeState,
    PageId,
    dashboard_home_state,
)
from .tasks import SerialTaskRunner


PAGE_SIZES = (50, 100, 250, 500, 1000)
FORM_COLUMNS = 4


class TableView(ttk.Frame):
    def __init__(self, parent, localization: LocalizationBindings, *, paged: bool = False):
        super().__init__(parent)
        self.localization = localization
        self.translator = localization.translator
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
        self.info = ttk.Label(footer)
        self.info.pack(side="left")
        self.next_button = ttk.Button(footer, state="disabled", command=self._go_next)
        self.previous_button = ttk.Button(
            footer, state="disabled", command=self._go_previous
        )
        self._info_binding = localization.bind(
            lambda value: self.info.configure(text=value), "empty.no_data"
        )
        localization.bind(
            lambda value: self.next_button.configure(text=value), "buttons.next"
        )
        localization.bind(
            lambda value: self.previous_button.configure(text=value), "buttons.previous"
        )
        localization.on_refresh(self._refresh_headings)
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
            heading = self._heading(column)
            self.tree.heading(column, text=heading)
            width = min(280, max(95, len(heading) * 9 + 24))
            self.tree.column(column, width=width, minwidth=70, stretch=True)
        for row in page.rows:
            self.tree.insert("", "end", values=row)
        start = (page.page - 1) * page.page_size + 1 if page.total_rows else 0
        end = min(page.page * page.page_size, page.total_rows)
        self._info_binding.update(
            "pagination.info",
            start=start,
            end=end,
            total=page.total_rows,
            page=page.page,
            pages=page.total_pages,
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

    def _heading(self, column: str) -> str:
        key = f"columns.{column}"
        return self.translator.t(key) if self.translator.has_key(key) else column

    def _refresh_headings(self) -> None:
        for column in self.current_page.columns:
            self.tree.heading(column, text=self._heading(column))


class ConsoleApp:
    def __init__(
        self,
        root: tk.Tk,
        backend: ConsoleBackend,
        settings_path: str,
        *,
        preference_store: UiPreferenceStore | None = None,
    ):
        self.root = root
        self.backend = backend
        self.settings_path = str(Path(settings_path).resolve())
        self.tasks = SerialTaskRunner()
        self._busy = False
        self.preference_store = preference_store or UiPreferenceStore()
        self.translator = Translator(self.preference_store.load_language())
        self.localization = LocalizationBindings(self.translator)
        self._status_mode = "status.ready"
        self._status_operation_key: str | None = None
        self._summary_states: dict[tk.StringVar, dict[str, Any]] = {}

        self.localization.bind(root.title, "app.title")
        configure_window_icon(root)
        root.geometry("1280x820")
        root.minsize(1100, 700)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._configure_style()

        self.status_text = tk.StringVar()
        self.error_text = tk.StringVar(value="")
        self._build_header()
        self._build_shell()
        self._build_status_bar()
        self.localization.on_refresh(self._refresh_dynamic_text)
        self._refresh_dynamic_text()

    def _build_shell(self) -> None:
        shell = ttk.Frame(self.root)
        shell.grid(row=1, column=0, sticky="nsew", padx=(14, 14), pady=(0, 8))

        self.sidebar = ttk.Frame(shell, style="Sidebar.TFrame", width=216)
        self.sidebar.pack(side="left", fill="y", padx=(0, 12))
        self.sidebar.pack_propagate(False)
        workspace = ttk.Frame(shell)
        workspace.pack(side="right", fill="both", expand=True)

        self.pages: dict[PageId, ttk.Frame] = {}
        self._page_ids_by_widget: dict[str, PageId] = {}
        self.navigation_buttons: dict[PageId, tk.Button] = {}
        self.navigation_indicators: dict[PageId, tk.Frame] = {}
        self.current_page_id = PageId.HOME
        self.notebook = ttk.Notebook(workspace, style="Hidden.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        self._build_dashboard()
        self._build_explorer()
        self._build_inventory()
        self._build_coverage_audit()
        self._build_intraday_audit()
        self._build_calendar()
        self._build_backfill()
        self._build_purge()
        self._build_runs()
        self._build_navigation()
        self._configure_fonts()
        self.notebook.bind("<<NotebookTabChanged>>", self._notebook_page_changed)
        self.select_page(PageId.HOME)

    def _configure_style(self) -> None:
        self.style = ttk.Style(self.root)
        available = self.style.theme_names()
        if "vista" in available:
            self.style.theme_use("vista")
        self.style.configure("Muted.TLabel", foreground="#5b6470")
        self.style.configure("Error.TLabel", foreground="#a4262c")
        self.style.configure("Network.TButton", foreground="#8a3b00")
        self.style.configure("Header.TFrame", background="#f7f7f7")
        self.style.configure("Sidebar.TFrame", background="#f2f2f2")
        self.style.configure(
            "NavigationGroup.TLabel",
            background="#f2f2f2",
            foreground="#626262",
        )
        self.style.layout("Hidden.TNotebook.Tab", [])
        self.style.configure("Hidden.TNotebook", borderwidth=0, tabmargins=0)
        self._configure_fonts()

    def _configure_fonts(self) -> None:
        family = choose_ui_font(self.translator.locale, set(tkfont.families(self.root)))
        self.style.configure("TLabel", font=(family, 9))
        self.style.configure("TButton", font=(family, 9))
        self.style.configure("TCheckbutton", font=(family, 9))
        self.style.configure("TNotebook.Tab", font=(family, 9))
        self.style.configure("TLabelframe.Label", font=(family, 9, "bold"))
        self.style.configure("Title.TLabel", font=(family, 18, "bold"))
        self.style.configure("Section.TLabel", font=(family, 12, "bold"))
        self.style.configure("Subsection.TLabel", font=(family, 11, "bold"))
        self.style.configure("Metric.TLabel", font=(family, 17, "bold"))
        self.style.configure("NavigationGroup.TLabel", font=(family, 8, "bold"))
        self.style.configure("Treeview", rowheight=25, font=(family, 9))
        self.style.configure("Treeview.Heading", font=(family, 9, "bold"))
        for button in getattr(self, "navigation_buttons", {}).values():
            button.configure(font=(family, 9))

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, padding=(16, 12), style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        identity = ttk.Frame(header, style="Header.TFrame")
        identity.pack(side="left")
        title = ttk.Label(identity, style="Title.TLabel", background="#f7f7f7")
        title.pack(anchor="w")
        self._bind_widget(title, "header.title")
        subtitle = ttk.Label(identity, style="Muted.TLabel", background="#f7f7f7")
        subtitle.pack(anchor="w")
        self._bind_widget(subtitle, "header.subtitle")
        context = ttk.Frame(header, style="Header.TFrame")
        context.pack(side="right")
        language_row = ttk.Frame(context, style="Header.TFrame")
        language_row.pack(anchor="e")
        local_mode = ttk.Label(language_row, style="Muted.TLabel", background="#f7f7f7")
        local_mode.pack(side="left", padx=(0, 12))
        self._bind_widget(local_mode, "header.local_mode")
        self.language_name = tk.StringVar(value=LANGUAGE_NAMES[self.translator.locale])
        self.language_selector = ttk.Combobox(
            language_row,
            textvariable=self.language_name,
            values=tuple(LANGUAGE_NAMES.values()),
            state="readonly",
            width=12,
        )
        self.language_selector.pack(side="left")
        self.language_selector.bind("<<ComboboxSelected>>", self._change_language)
        settings_context = ttk.Label(
            context, style="Muted.TLabel", background="#f7f7f7"
        )
        settings_context.pack(anchor="e", pady=(4, 0))
        self.localization.bind(
            lambda value: settings_context.configure(text=value),
            "header.settings_path",
            settings_path=self.settings_path,
        )

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self.root, padding=(14, 6))
        bar.grid(row=2, column=0, sticky="ew")
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        self.progress.pack(side="right")
        ttk.Label(bar, textvariable=self.status_text).pack(side="left")
        ttk.Label(bar, textvariable=self.error_text, style="Error.TLabel").pack(side="left", padx=16)

    def _new_tab(self, page_id: PageId) -> ttk.Frame:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="")
        self.pages[page_id] = tab
        self._page_ids_by_widget[str(tab)] = page_id
        self.localization.bind(
            lambda value: self.notebook.tab(tab, text=value), PAGE_TAB_KEYS[page_id]
        )
        return tab

    def _build_navigation(self) -> None:
        for group_index, group in enumerate(NAVIGATION_GROUPS):
            if group.label_key is not None:
                group_label = ttk.Label(self.sidebar, style="NavigationGroup.TLabel")
                group_label.pack(fill="x", padx=14, pady=(12, 4))
                self._bind_widget(group_label, group.label_key)
            elif group_index == 0:
                ttk.Frame(self.sidebar, style="Sidebar.TFrame", height=8).pack(fill="x")
            for item in group.items:
                row = tk.Frame(self.sidebar, background="#f2f2f2", height=36)
                row.pack(fill="x")
                row.pack_propagate(False)
                indicator = tk.Frame(row, width=3, background="#f2f2f2")
                indicator.pack(side="left", fill="y")
                button = tk.Button(
                    row,
                    anchor="w",
                    background="#f2f2f2",
                    activebackground="#e7e7e7",
                    activeforeground="#202020",
                    borderwidth=0,
                    cursor="hand2",
                    foreground="#303030",
                    highlightthickness=0,
                    padx=12,
                    relief="flat",
                    takefocus=True,
                    command=lambda page_id=item.page_id: self.select_page(page_id),
                )
                button.pack(side="left", fill="both", expand=True)
                self.localization.bind(
                    lambda value, widget=button: widget.configure(text=value),
                    item.label_key,
                )
                self.navigation_buttons[item.page_id] = button
                self.navigation_indicators[item.page_id] = indicator

    def select_page(self, page_id: PageId | str) -> None:
        normalized = PageId(page_id)
        self.notebook.select(self.pages[normalized])
        self.current_page_id = normalized
        self._refresh_navigation_selection()

    def _notebook_page_changed(self, _event=None) -> None:
        selected = self.notebook.select()
        page_id = self._page_ids_by_widget.get(str(selected))
        if page_id is not None:
            self.current_page_id = page_id
            self._refresh_navigation_selection()

    def _refresh_navigation_selection(self) -> None:
        for page_id, button in self.navigation_buttons.items():
            selected = page_id == self.current_page_id
            button.configure(
                background="#eee6d2" if selected else "#f2f2f2",
                activebackground="#e8dfc8" if selected else "#e7e7e7",
                foreground="#4f3b08" if selected else "#303030",
            )
            self.navigation_indicators[page_id].configure(
                background="#b48a28" if selected else "#f2f2f2"
            )

    def _build_dashboard(self) -> None:
        tab = self._new_tab(PageId.HOME)
        top = ttk.Frame(tab)
        top.pack(fill="x")
        overview = ttk.Label(top, style="Section.TLabel")
        overview.pack(side="left")
        self._bind_widget(overview, "home.title")
        refresh = ttk.Button(top, command=self._refresh_dashboard)
        refresh.pack(side="right")
        self._bind_widget(refresh, "buttons.refresh")

        self.home_summary = ttk.Frame(tab)
        self.home_summary.pack(fill="x", pady=(10, 12))
        self.home_message = ttk.Label(
            self.home_summary, style="Muted.TLabel", justify="left", wraplength=700
        )
        self.home_message.pack(anchor="w")
        self.home_message_binding = self.localization.bind(
            lambda value: self.home_message.configure(text=value), "home.unloaded.body"
        )
        self.home_quick_actions = ttk.Frame(self.home_summary)
        self.home_quick_actions.pack(anchor="w", pady=(10, 0))
        self._button(
            self.home_quick_actions,
            "navigation.items.historical_data",
            lambda: self.select_page(PageId.HISTORICAL_DATA),
        ).pack(side="left")
        self._button(
            self.home_quick_actions,
            "navigation.items.trading_calendar",
            lambda: self.select_page(PageId.TRADING_CALENDAR),
        ).pack(side="left", padx=(8, 0))

        self.dashboard_metrics = ttk.Frame(self.home_summary)
        self.metric_values: dict[str, tk.StringVar] = {}
        for index, (name, key) in enumerate(HOME_METRICS):
            panel = ttk.LabelFrame(self.dashboard_metrics, padding=10)
            panel.grid(
                row=index // 3,
                column=index % 3,
                padx=(0, 8),
                pady=(0, 8),
                sticky="nsew",
            )
            self._bind_widget(panel, key)
            value = tk.StringVar(value="-")
            self.metric_values[name] = value
            ttk.Label(panel, textvariable=value, style="Metric.TLabel").pack()
            self.dashboard_metrics.columnconfigure(index % 3, weight=1)
        self.home_state = HomeState.UNLOADED
        recent = ttk.Label(tab, style="Subsection.TLabel")
        recent.pack(anchor="w", pady=(8, 6))
        self._bind_widget(recent, "sections.recent_runs")
        self.dashboard_runs = TableView(tab, self.localization)
        self.dashboard_runs.pack(fill="both", expand=True)

    def _build_explorer(self) -> None:
        tab = self._new_tab(PageId.MARKET_DATA)
        form = ttk.LabelFrame(tab, padding=10)
        form.pack(fill="x")
        self._bind_widget(form, "sections.explorer")
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
        self._entry(form, "fields.code", self.explorer_vars["code"], 0)
        self._entry(form, "fields.start_date", self.explorer_vars["start_date"], 1)
        self._entry(form, "fields.end_date", self.explorer_vars["end_date"], 2)
        self._combo(form, "fields.interval", self.explorer_vars["interval"], ("1m", "5m", "15m", "30m", "60m", "day"), 3)
        self._combo(form, "fields.requested_session", self.explorer_vars["requested_session"], ("", "ALL", "RTH", "ETH"), 4)
        self._combo(form, "fields.bar_session", self.explorer_vars["bar_session"], ("", "OVERNIGHT", "PRE_MARKET", "REGULAR", "AFTER_HOURS"), 5)
        self._combo(form, "fields.adjustment", self.explorer_vars["adjustment"], ("NONE", "QFQ", "HFQ"), 6)
        self._combo(form, "fields.page_size", self.explorer_vars["page_size"], PAGE_SIZES, 7)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        self._button(actions, "buttons.query", lambda: self._query_explorer(1)).pack(side="left")
        self._button(actions, "buttons.export_csv", lambda: self._export(self.explorer_table, "csv")).pack(side="left", padx=6)
        self._button(actions, "buttons.export_json", lambda: self._export(self.explorer_table, "json")).pack(side="left")
        self.explorer_table = TableView(tab, self.localization, paged=True)
        self.explorer_table.pack(fill="both", expand=True)

    def _build_inventory(self) -> None:
        tab = self._new_tab(PageId.INVENTORY)
        form = ttk.LabelFrame(tab, padding=10)
        form.pack(fill="x")
        self._bind_widget(form, "sections.inventory")
        self.inventory_vars = {
            "symbols": tk.StringVar(),
            "start_date": tk.StringVar(),
            "end_date": tk.StringVar(),
            "interval": tk.StringVar(),
            "session": tk.StringVar(),
            "adjustment": tk.StringVar(),
        }
        for index, key in enumerate(self.inventory_vars):
            self._entry(form, f"fields.{key}", self.inventory_vars[key], index)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        self._button(actions, "buttons.run_inventory", self._run_inventory).pack(side="left")
        self._button(actions, "buttons.export_csv", lambda: self._export(self.inventory_table, "csv")).pack(side="left", padx=6)
        self.inventory_summary = tk.StringVar()
        self.inventory_summary_binding = self.localization.bind(
            self.inventory_summary.set, "empty.no_inventory"
        )
        ttk.Label(actions, textvariable=self.inventory_summary, style="Muted.TLabel").pack(side="left", padx=14)
        self.inventory_table = TableView(tab, self.localization)
        self.inventory_table.pack(fill="both", expand=True)

    def _build_coverage_audit(self) -> None:
        tab = self._new_tab(PageId.COVERAGE_AUDIT)
        self.coverage_vars = self._audit_form(tab, "sections.coverage")
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        self._button(actions, "buttons.run_coverage", self._run_coverage).pack(side="left")
        self._button(actions, "buttons.export_csv", lambda: self._export(self.coverage_table, "csv")).pack(side="left", padx=6)
        self.coverage_summary = tk.StringVar()
        self.coverage_summary_binding = self.localization.bind(
            self.coverage_summary.set, "empty.no_audit"
        )
        ttk.Label(actions, textvariable=self.coverage_summary, style="Muted.TLabel").pack(side="left", padx=14)
        self.coverage_table = TableView(tab, self.localization)
        self.coverage_table.pack(fill="both", expand=True)

    def _build_intraday_audit(self) -> None:
        tab = self._new_tab(PageId.INTRADAY_AUDIT)
        self.intraday_vars = self._audit_form(tab, "sections.intraday")
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        self._button(actions, "buttons.run_intraday", self._run_intraday).pack(side="left")
        self._button(actions, "buttons.export_csv", lambda: self._export(self.intraday_table, "csv")).pack(side="left", padx=6)
        self.intraday_summary = tk.StringVar()
        self.intraday_summary_binding = self.localization.bind(
            self.intraday_summary.set, "empty.no_audit"
        )
        ttk.Label(actions, textvariable=self.intraday_summary, style="Muted.TLabel").pack(side="left", padx=14)
        self.intraday_table = TableView(tab, self.localization)
        self.intraday_table.pack(fill="both", expand=True)

    def _audit_form(self, tab: ttk.Frame, title_key: str) -> dict[str, tk.StringVar]:
        form = ttk.LabelFrame(tab, padding=10)
        form.pack(fill="x")
        self._bind_widget(form, title_key)
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
            self._entry(form, f"fields.{key}", values[key], index)
        return values

    def _build_calendar(self) -> None:
        tab = self._new_tab(PageId.TRADING_CALENDAR)
        form = ttk.LabelFrame(tab, padding=10)
        form.pack(fill="x")
        self._bind_widget(form, "sections.calendar")
        self.calendar_vars = {
            "scope": tk.StringVar(value="MARKET"),
            "market": tk.StringVar(value="US"),
            "code": tk.StringVar(),
            "start_date": tk.StringVar(),
            "end_date": tk.StringVar(),
            "page_size": tk.IntVar(value=100),
        }
        self._combo(form, "fields.scope", self.calendar_vars["scope"], ("MARKET", "CODE"), 0)
        self._entry(form, "fields.market", self.calendar_vars["market"], 1)
        self._entry(form, "fields.code", self.calendar_vars["code"], 2)
        self._entry(form, "fields.start_date", self.calendar_vars["start_date"], 3)
        self._entry(form, "fields.end_date", self.calendar_vars["end_date"], 4)
        self._combo(form, "fields.page_size", self.calendar_vars["page_size"], PAGE_SIZES, 5)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        self._button(actions, "buttons.query_local", lambda: self._query_calendar(1)).pack(side="left")
        self._button(
            actions, "buttons.fetch_opend", self._collect_calendar, style="Network.TButton"
        ).pack(side="left", padx=6)
        self._button(actions, "buttons.export_csv", lambda: self._export(self.calendar_table, "csv")).pack(side="left")
        self.calendar_table = TableView(tab, self.localization, paged=True)
        self.calendar_table.pack(fill="both", expand=True)

    def _build_backfill(self) -> None:
        tab = self._new_tab(PageId.HISTORICAL_DATA)
        form = ttk.LabelFrame(tab, padding=10)
        form.pack(fill="x")
        self._bind_widget(form, "sections.backfill")
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
            self._entry(form, f"fields.{key}", self.backfill_vars[key], index)
        flags = ttk.Frame(form)
        flags.grid(row=2, column=0, columnspan=8, sticky="w", pady=(8, 0))
        incremental = ttk.Checkbutton(flags, variable=self.backfill_vars["incremental"])
        incremental.pack(side="left")
        self._bind_widget(incremental, "checkbox.incremental")
        force = ttk.Checkbutton(flags, variable=self.backfill_vars["force"])
        force.pack(side="left", padx=12)
        self._bind_widget(force, "checkbox.force")
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        self._button(actions, "buttons.plan_local", self._plan_backfill).pack(side="left")
        self._button(
            actions, "buttons.execute_opend", self._execute_backfill, style="Network.TButton"
        ).pack(side="left", padx=6)
        self.backfill_summary = tk.StringVar()
        self.backfill_summary_binding = self.localization.bind(
            self.backfill_summary.set, "empty.no_plan"
        )
        ttk.Label(actions, textvariable=self.backfill_summary, style="Muted.TLabel").pack(side="left", padx=14)
        self.backfill_table = TableView(tab, self.localization)
        self.backfill_table.pack(fill="both", expand=True)

    def _build_runs(self) -> None:
        tab = self._new_tab(PageId.RUNS)
        form = ttk.LabelFrame(tab, padding=10)
        form.pack(fill="x")
        self._bind_widget(form, "sections.runs")
        self.runs_vars = {
            "status": tk.StringVar(),
            "dataset": tk.StringVar(),
            "page_size": tk.IntVar(value=100),
        }
        self._combo(form, "fields.status", self.runs_vars["status"], ("", "RUNNING", "SUCCESS", "PARTIAL", "FAILED"), 0)
        self._entry(form, "fields.dataset", self.runs_vars["dataset"], 1)
        self._combo(form, "fields.page_size", self.runs_vars["page_size"], PAGE_SIZES, 2)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=8)
        self._button(actions, "buttons.refresh", lambda: self._query_runs(1)).pack(side="left")
        self._button(actions, "buttons.export_csv", lambda: self._export(self.runs_table, "csv")).pack(side="left", padx=6)
        self.runs_table = TableView(tab, self.localization, paged=True)
        self.runs_table.pack(fill="both", expand=True)

    def _build_purge(self) -> None:
        tab = self._new_tab(PageId.STORAGE_CLEANUP)
        form = ttk.LabelFrame(tab, padding=10)
        form.pack(fill="x")
        self._bind_widget(form, "sections.purge")
        self.purge_vars = {
            "source": tk.StringVar(value=self.backend.vault.settings.source),
            "symbols": tk.StringVar(value="US.SPY"),
            "start_date": tk.StringVar(),
            "end_date": tk.StringVar(),
            "interval": tk.StringVar(value="1m"),
            "session": tk.StringVar(value="ALL"),
            "adjustment": tk.StringVar(value="NONE"),
            "source_schema_version": tk.StringVar(
                value=self.backend.vault.settings.source_schema_version
            ),
        }
        for index, key in enumerate(self.purge_vars):
            self._entry(form, f"fields.{key}", self.purge_vars[key], index)
        review = ttk.Frame(tab)
        review.pack(fill="x", pady=8)
        self._button(review, "buttons.preview_purge", self._preview_purge).pack(side="left")
        self.purge_summary = tk.StringVar()
        self.purge_summary_binding = self.localization.bind(
            self.purge_summary.set, "empty.no_purge_plan"
        )
        ttk.Label(review, textvariable=self.purge_summary, style="Muted.TLabel").pack(
            side="left", padx=14
        )
        self.purge_refusals = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.purge_refusals, style="Error.TLabel").pack(
            fill="x", anchor="w"
        )
        self.purge_table = TableView(tab, self.localization)
        self.purge_table.pack(fill="both", expand=True)
        confirmation = ttk.LabelFrame(tab, padding=10)
        confirmation.pack(fill="x", pady=(8, 0))
        self._bind_widget(confirmation, "sections.purge_execute")
        description = ttk.Label(confirmation, wraplength=720)
        description.pack(anchor="w")
        self._bind_widget(description, "purge.description")
        row = ttk.Frame(confirmation)
        row.pack(fill="x", pady=(8, 0))
        confirmation_label = ttk.Label(row)
        confirmation_label.pack(side="left")
        self._bind_widget(confirmation_label, "purge.confirmation")
        self.purge_confirmation = tk.StringVar()
        ttk.Entry(row, textvariable=self.purge_confirmation, width=46).pack(
            side="left", padx=8
        )
        self.purge_execute_button = ttk.Button(
            row,
            state="disabled",
            command=self._execute_purge,
        )
        self.purge_execute_button.pack(side="left")
        self._bind_widget(self.purge_execute_button, "buttons.move_quarantine")
        self._purge_plan_id: str | None = None
        self._bind_purge_scope_invalidation()

    def _bind_purge_scope_invalidation(self) -> None:
        for variable in self.purge_vars.values():
            variable.trace_add("write", self._invalidate_purge_review)

    def _invalidate_purge_review(self, *_args) -> None:
        """Require a fresh sealed Preview after any scope field changes."""
        self._purge_plan_id = None
        self.backend.invalidate_purge_preview()
        self.purge_confirmation.set("")
        self.purge_execute_button.configure(state="disabled")
        binding = getattr(self, "purge_summary_binding", None)
        if binding is not None:
            binding.update("purge.scope_changed")
        else:
            self.purge_summary.set("Scope changed; run Preview again")
        self.purge_refusals.set("")

    def _bind_widget(self, widget, key: str, **values) -> TextBinding:
        return self.localization.bind(
            lambda text, target=widget: target.configure(text=text), key, **values
        )

    def _button(self, parent, key: str, command, *, style: str | None = None):
        kwargs = {"command": command}
        if style is not None:
            kwargs["style"] = style
        button = ttk.Button(parent, **kwargs)
        self._bind_widget(button, key)
        return button

    def _entry(self, parent, label_key: str, variable: tk.Variable, column: int) -> None:
        frame = ttk.Frame(parent)
        frame.grid(
            row=column // FORM_COLUMNS,
            column=column % FORM_COLUMNS,
            padx=(0, 8),
            pady=(0, 6),
            sticky="ew",
        )
        label = ttk.Label(frame)
        label.pack(anchor="w")
        self._bind_widget(label, label_key)
        ttk.Entry(frame, textvariable=variable, width=17).pack(fill="x")
        parent.columnconfigure(column % FORM_COLUMNS, weight=1)

    def _combo(self, parent, label_key: str, variable: tk.Variable, values, column: int) -> None:
        frame = ttk.Frame(parent)
        frame.grid(
            row=column // FORM_COLUMNS,
            column=column % FORM_COLUMNS,
            padx=(0, 8),
            pady=(0, 6),
            sticky="ew",
        )
        label = ttk.Label(frame)
        label.pack(anchor="w")
        self._bind_widget(label, label_key)
        ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", width=15).pack(fill="x")
        parent.columnconfigure(column % FORM_COLUMNS, weight=1)

    def _change_language(self, _event=None) -> None:
        locale = LOCALES_BY_NAME.get(self.language_name.get(), "en")
        self.preference_store.save_language(locale)
        self.localization.set_locale(locale)
        self._configure_fonts()
        self.root.update_idletasks()

    def _refresh_dynamic_text(self) -> None:
        if self._status_operation_key is None:
            self.status_text.set(self.translator.t(self._status_mode))
        else:
            self.status_text.set(
                self.translator.t(
                    self._status_mode,
                    operation=self.translator.t(self._status_operation_key),
                )
            )
        for variable, summary in self._summary_states.items():
            variable.set(self._summary_text(summary))

    def _set_status(self, key: str, operation_key: str | None = None) -> None:
        self._status_mode = key
        self._status_operation_key = operation_key
        self._refresh_dynamic_text()

    def _set_summary(self, variable: tk.StringVar, summary: dict[str, Any]) -> None:
        self._summary_states[variable] = dict(summary)
        variable.set(self._summary_text(summary))

    def _submit(
        self,
        operation_key: str,
        operation: Callable[[], Any],
        success: Callable[[Any], None],
        *,
        requires_opend: bool = False,
    ) -> None:
        if self._busy:
            messagebox.showinfo(
                self.translator.t("dialog.running.title"),
                self.translator.t("dialog.running.body"),
            )
            return
        if requires_opend:
            settings = self.backend.vault.settings
            confirmed = messagebox.askyesno(
                self.translator.t("dialog.opend.title"),
                self.translator.t(
                    "dialog.opend.body",
                    operation=self.translator.t(operation_key),
                    host=settings.opend_host,
                    port=settings.opend_port,
                ),
            )
            if not confirmed:
                return
        self._busy = True
        self.error_text.set("")
        self._set_status("status.running", operation_key)
        self.progress.start(12)
        try:
            future = self.tasks.submit(operation_key, operation)
        except Exception as exc:
            self._finish_error(operation_key, exc)
            return
        self._poll_future(future, operation_key, success)

    def _poll_future(self, future: Future[Any], operation_key: str, success: Callable[[Any], None]) -> None:
        if not future.done():
            self.root.after(100, self._poll_future, future, operation_key, success)
            return
        self._busy = False
        self.progress.stop()
        try:
            result = future.result()
            success(result)
            self._set_status("status.completed", operation_key)
        except Exception as exc:
            self._finish_error(operation_key, exc)

    def _finish_error(self, operation_key: str, exc: Exception) -> None:
        self._busy = False
        self.progress.stop()
        self._set_status("status.failed", operation_key)
        self.error_text.set(str(exc))
        messagebox.showerror(self.translator.t(operation_key), str(exc))

    def _refresh_dashboard(self) -> None:
        def success(snapshot: DashboardSnapshot) -> None:
            for name, _key in HOME_METRICS:
                self.metric_values[name].set(snapshot.metrics.get(name, "-"))
            self.dashboard_runs.set_page(snapshot.recent_runs)
            self._set_home_state(dashboard_home_state(snapshot))

        self._submit("operations.dashboard_refresh", self.backend.dashboard, success)

    def _set_home_state(self, state: HomeState) -> None:
        self.home_state = state
        if state == HomeState.POPULATED:
            self.home_message.pack_forget()
            self.home_quick_actions.pack_forget()
            self.dashboard_metrics.pack(fill="x")
            return

        self.dashboard_metrics.pack_forget()
        message_key = (
            "home.empty.body" if state == HomeState.EMPTY else "home.unloaded.body"
        )
        self.home_message_binding.update(message_key)
        self.home_message.pack(anchor="w")
        self.home_quick_actions.pack(anchor="w", pady=(10, 0))

    def _query_explorer(self, page: int) -> None:
        values = {key: variable.get() for key, variable in self.explorer_vars.items()}

        def success(result: TablePage) -> None:
            self.explorer_table.set_page(
                result,
                previous=lambda: self._query_explorer(page - 1),
                next_=lambda: self._query_explorer(page + 1),
            )

        self._submit("operations.market_bar_query", lambda: self.backend.query_bars(page=page, **values), success)

    def _run_inventory(self) -> None:
        values = {key: variable.get() for key, variable in self.inventory_vars.items()}

        def success(result) -> None:
            summary, table = result
            self._set_summary(self.inventory_summary, summary)
            self.inventory_table.set_page(table)

        self._submit("operations.inventory", lambda: self.backend.inventory(**values), success)

    def _run_coverage(self) -> None:
        values = {key: variable.get() for key, variable in self.coverage_vars.items()}

        def success(result) -> None:
            summary, table = result
            self._set_summary(self.coverage_summary, summary)
            self.coverage_table.set_page(table)

        self._submit("operations.coverage_audit", lambda: self.backend.coverage_audit(**values), success)

    def _run_intraday(self) -> None:
        values = {key: variable.get() for key, variable in self.intraday_vars.items()}

        def success(result) -> None:
            summary, table = result
            self._set_summary(self.intraday_summary, summary)
            self.intraday_table.set_page(table)

        self._submit("operations.intraday_audit", lambda: self.backend.intraday_audit(**values), success)

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

        self._submit("operations.calendar_query", lambda: self.backend.query_calendar(page=page, **values), success)

    def _collect_calendar(self) -> None:
        market, code = self._calendar_scope()
        values = {
            "market": market,
            "code": code,
            "start_date": self.calendar_vars["start_date"].get(),
            "end_date": self.calendar_vars["end_date"].get(),
        }

        def success(manifest: dict[str, Any]) -> None:
            self.root.after(50, self._query_calendar, 1)

        self._submit(
            "operations.calendar_fetch",
            lambda: self.backend.collect_calendar(**values),
            success,
            requires_opend=True,
        )

    def _backfill_values(self) -> dict[str, Any]:
        return {key: variable.get() for key, variable in self.backfill_vars.items()}

    def _plan_backfill(self) -> None:
        values = self._backfill_values()

        def success(plan: BackfillPlanView) -> None:
            self.backfill_summary_binding.update(
                "summary.backfill_plan",
                scope=plan.scope,
                dates=plan.trading_date_count,
                pending=plan.pending_count,
                skipped=plan.skipped_count,
            )
            self.backfill_table.set_page(plan.items)

        self._submit("operations.backfill_plan", lambda: self.backend.plan_backfill(**values), success)

    def _execute_backfill(self) -> None:
        values = self._backfill_values()

        def success(manifest: dict[str, Any]) -> None:
            parameters = manifest.get("parameters", {})
            self.backfill_summary_binding.update(
                "summary.backfill_result",
                status=manifest.get("status"),
                run_id=manifest.get("run_id"),
                success=parameters.get("successful_item_count", 0),
                failed=parameters.get("failed_item_count", 0),
            )

        self._submit(
            "operations.backfill_execute",
            lambda: self.backend.execute_backfill(**values),
            success,
            requires_opend=True,
        )

    def _preview_purge(self) -> None:
        values = {key: variable.get() for key, variable in self.purge_vars.items()}
        self._purge_plan_id = None
        self.purge_execute_button.configure(state="disabled")
        self.purge_confirmation.set("")

        def success(plan: PurgePlanView) -> None:
            self.purge_table.set_page(plan.items)
            summary = plan.summary
            self.purge_summary_binding.update(
                "summary.purge_plan",
                status=plan.status,
                plan_id=plan.plan_id,
                pairs=summary.get("affected_snapshot_count", 0),
                rows=summary.get("affected_row_count", 0),
            )
            refusal_text = []
            for reason in plan.refusal_reasons:
                detail = reason.get("symbols") or reason.get("outside_dates") or ""
                refusal_text.append(f"{reason.get('code')}: {reason.get('message')} {detail}")
            self.purge_refusals.set(" | ".join(refusal_text))
            if plan.executable:
                self._purge_plan_id = plan.plan_id
                self.purge_execute_button.configure(state="normal")

        self._submit("operations.purge_preview", lambda: self.backend.preview_purge(**values), success)

    def _execute_purge(self) -> None:
        if not self._purge_plan_id:
            messagebox.showerror(
                self.translator.t("dialog.purge.title"),
                self.translator.t("dialog.purge.preview_first"),
            )
            return
        plan_id = self._purge_plan_id
        confirmation = self.purge_confirmation.get()

        def success(result: dict[str, Any]) -> None:
            self.purge_summary_binding.update(
                "summary.purge_result",
                status=result.get("status"),
                plan_id=result.get("plan_id"),
                files=len(result.get("moved_files", [])),
            )
            self._purge_plan_id = None
            self.purge_execute_button.configure(state="disabled")

        self._submit(
            "operations.purge_execute",
            lambda: self.backend.execute_purge(
                plan_id=plan_id,
                confirmation=confirmation,
            ),
            success,
        )

    def _query_runs(self, page: int) -> None:
        values = {key: variable.get() for key, variable in self.runs_vars.items()}

        def success(result: TablePage) -> None:
            self.runs_table.set_page(
                result,
                previous=lambda: self._query_runs(page - 1),
                next_=lambda: self._query_runs(page + 1),
            )

        self._submit("operations.run_history", lambda: self.backend.runs(page=page, **values), success)

    def _export(self, table: TableView, format_name: str) -> None:
        if not table.current_page.columns:
            messagebox.showinfo(
                self.translator.t("dialog.export.title"),
                self.translator.t("dialog.export.no_data"),
            )
            return
        extension = ".csv" if format_name == "csv" else ".json"
        path = filedialog.asksaveasfilename(
            defaultextension=extension,
            filetypes=[(format_name.upper(), f"*{extension}")],
        )
        if not path:
            return

        def success(result) -> None:
            messagebox.showinfo(
                self.translator.t("dialog.export.complete_title"),
                self.translator.t(
                    "dialog.export.complete_body",
                    row_count=result.row_count,
                    path=result.path,
                ),
            )

        self._submit(
            "operations.export_page",
            lambda: self.backend.export_page(table.current_page, path, format_name),
            success,
        )

    def _summary_text(self, summary: dict[str, Any]) -> str:
        preferred = (
            "status",
            "calendar_coverage_complete",
            "failure_reason",
            "calendar_coverage_gaps",
            "symbol_count",
            "snapshot_count",
            "total_expected_items",
            "complete_item_count",
            "audited_item_count",
            "warn_item_count",
            "fail_item_count",
            "coverage_percentage",
        )
        parts = [
            f"{self.translator.t(f'summary.{key}')}={summary[key]}"
            for key in preferred
            if key in summary
        ]
        if not parts:
            parts = [f"{key}={value}" for key, value in list(summary.items())[:6]]
        return " | ".join(parts)

    def _close(self) -> None:
        if self._busy:
            messagebox.showinfo(
                self.translator.t("dialog.running.title"),
                self.translator.t("dialog.running.close_body"),
            )
            return
        self.tasks.close()
        self.root.destroy()


def run_console(settings_path: str) -> int:
    preference_store = UiPreferenceStore()
    translator = Translator(preference_store.load_language())
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(translator.t("startup.tk_unavailable", details=exc), file=sys.stderr)
        return 1
    try:
        backend = ConsoleBackend.from_settings(settings_path)
    except Exception as exc:
        root.withdraw()
        messagebox.showerror(translator.t("app.title"), str(exc))
        root.destroy()
        return 1
    ConsoleApp(root, backend, settings_path, preference_store=preference_store)
    root.mainloop()
    return 0
