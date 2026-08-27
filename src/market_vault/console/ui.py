from __future__ import annotations

import math
import sys
import tkinter as tk
from concurrent.futures import Future
from pathlib import Path, PurePosixPath, PureWindowsPath
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
HOME_METRIC_COLUMNS = 3

APP_BG = "#EEEAE0"
HEADER_BG = "#F8F5ED"
SIDEBAR_BG = "#E5E0D4"
WORKSPACE_BG = "#F5F1E8"
CARD_BG = "#FBF8F0"
CARD_BORDER = "#C8B98F"
CARD_HIGHLIGHT = "#FFFDF7"
GOLD = "#B58A2A"
GOLD_DARK = "#80601B"
GOLD_SOFT = "#EEE6D2"
TEXT_PRIMARY = "#282722"
TEXT_SECONDARY = "#777166"
NAV_HOVER = "#ECE6D9"
NAV_SELECTED = "#F2E7C9"
STATUS_BG = "#E9E3D6"
ERROR = "#A4262C"
WARNING = "#8A3B00"

TABLE_BG = CARD_BG
TABLE_ALT_BG = "#F7F2E7"
TABLE_HEADER_BG = GOLD_SOFT
TABLE_HEADER_TEXT = GOLD_DARK
TABLE_SELECTION_BG = NAV_SELECTED
TABLE_SELECTION_TEXT = TEXT_PRIMARY
TABLE_ROWHEIGHT = 29

AMBIENT_UPDATE_INTERVAL_MS = 120
AMBIENT_MAX_GLYPHS = 1200
AMBIENT_GLYPH_SPACING = 22
AMBIENT_REGION_HEIGHT = 92
AMBIENT_PHASE_STEP = 0.018
AMBIENT_NEUTRAL = "#716A5C"
AMBIENT_GOLD = GOLD
AMBIENT_VERMILION = "#9A6752"
AMBIENT_SAGE = "#71806C"


def blend_color(foreground: str, background: str, alpha: float) -> str:
    """Preblend a foreground color for Tk widgets without alpha support."""

    bounded_alpha = min(1.0, max(0.0, float(alpha)))

    def channels(value: str) -> tuple[int, int, int]:
        if len(value) != 7 or not value.startswith("#"):
            raise ValueError(f"expected #RRGGBB color, got {value!r}")
        try:
            return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))
        except ValueError as exc:
            raise ValueError(f"expected #RRGGBB color, got {value!r}") from exc

    foreground_rgb = channels(foreground)
    background_rgb = channels(background)
    mixed = tuple(
        round(
            foreground_channel * bounded_alpha
            + background_channel * (1.0 - bounded_alpha)
        )
        for foreground_channel, background_channel in zip(
            foreground_rgb, background_rgb, strict=True
        )
    )
    return "#" + "".join(f"{channel:02X}" for channel in mixed)


def ambient_field_value(x: float, y: float, phase: float) -> float:
    """Return a deterministic, spatially and temporally continuous field."""

    return (
        math.sin(x * 0.31 + phase * 0.73)
        + math.sin(y * 0.37 - phase * 0.51)
        + math.sin((x + y) * 0.19 + phase * 0.29)
        + math.cos((x - y) * 0.23 - phase * 0.41)
    ) / 4.0


def ambient_digit(x: float, y: float, phase: float) -> str:
    """Discretize the continuous field into the only allowed glyphs."""

    threshold = 0.08 * math.sin(x * 0.11 - y * 0.13 + phase * 0.17)
    return "1" if ambient_field_value(x, y, phase) > threshold else "0"


def ambient_visibility(horizontal_fraction: float) -> float:
    """Smoothly fade the field from nearly hidden left to visible right."""

    normalized = min(1.0, max(0.0, float(horizontal_fraction)))
    progress = min(1.0, max(0.0, (normalized - 0.12) / 0.33))
    return progress * progress * (3.0 - 2.0 * progress)


def ambient_fill(x: float, y: float, phase: float, horizontal_fraction: float) -> str:
    """Return a low-contrast preblended color for one ambient glyph."""

    visibility = ambient_visibility(horizontal_fraction)
    color_field = ambient_field_value(x * 0.61 + 5.0, y * 0.67 - 3.0, phase * 0.63)
    if color_field > 0.72:
        foreground, maximum_alpha = AMBIENT_VERMILION, 0.14
    elif color_field < -0.74:
        foreground, maximum_alpha = AMBIENT_SAGE, 0.14
    elif color_field > 0.28:
        foreground, maximum_alpha = AMBIENT_GOLD, 0.25
    else:
        foreground, maximum_alpha = AMBIENT_NEUTRAL, 0.20
    return blend_color(foreground, WORKSPACE_BG, visibility * maximum_alpha)


def ambient_grid_positions(
    width: int,
    height: int,
    *,
    spacing: int = AMBIENT_GLYPH_SPACING,
    max_glyphs: int = AMBIENT_MAX_GLYPHS,
) -> tuple[tuple[int, int, int, int, float], ...]:
    """Return a bounded deterministic grid for a canvas size."""

    safe_width = max(0, int(width))
    safe_height = max(0, int(height))
    safe_spacing = max(8, int(spacing))
    safe_cap = max(1, int(max_glyphs))
    columns = max(1, safe_width // safe_spacing) if safe_width else 0
    rows = max(1, safe_height // safe_spacing) if safe_height else 0
    if columns * rows > safe_cap:
        scale = math.sqrt((columns * rows) / safe_cap)
        safe_spacing = max(safe_spacing, math.ceil(safe_spacing * scale))
        columns = max(1, safe_width // safe_spacing) if safe_width else 0
        rows = max(1, safe_height // safe_spacing) if safe_height else 0

    positions = []
    for row in range(rows):
        for column in range(columns):
            if len(positions) >= safe_cap:
                return tuple(positions)
            x_position = min(safe_width - 1, safe_spacing // 2 + column * safe_spacing)
            y_position = min(safe_height - 1, safe_spacing // 2 + row * safe_spacing)
            horizontal_fraction = x_position / max(1, safe_width - 1)
            positions.append(
                (column, row, x_position, y_position, horizontal_fraction)
            )
    return tuple(positions)


def _configure_table_elements(style: ttk.Style) -> None:
    """Use colorable scoped elements without changing the application theme."""

    if "clam" not in style.theme_names():
        return
    elements = (
        ("MarketVault.Treeview.field", "Treeview.field"),
        ("MarketVault.Treeview.padding", "Treeview.padding"),
        ("MarketVault.Treeview.treearea", "Treeview.treearea"),
        ("MarketVault.Treeheading.cell", "Treeheading.cell"),
        ("MarketVault.Treeheading.border", "Treeheading.border"),
        ("MarketVault.Treeheading.padding", "Treeheading.padding"),
        ("MarketVault.Treeheading.image", "Treeheading.image"),
        ("MarketVault.Treeheading.text", "Treeheading.text"),
    )
    existing = set(style.element_names())
    for target, source in elements:
        if target not in existing:
            style.element_create(target, "from", "clam", source)
    style.layout(
        "MarketVault.Treeview",
        [
            (
                "MarketVault.Treeview.field",
                {
                    "sticky": "nswe",
                    "border": "1",
                    "children": [
                        (
                            "MarketVault.Treeview.padding",
                            {
                                "sticky": "nswe",
                                "children": [
                                    ("MarketVault.Treeview.treearea", {"sticky": "nswe"})
                                ],
                            },
                        )
                    ],
                },
            )
        ],
    )
    style.layout(
        "MarketVault.Treeview.Heading",
        [
            ("MarketVault.Treeheading.cell", {"sticky": "nswe"}),
            (
                "MarketVault.Treeheading.border",
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "MarketVault.Treeheading.padding",
                            {
                                "sticky": "nswe",
                                "children": [
                                    (
                                        "MarketVault.Treeheading.image",
                                        {"side": "right", "sticky": ""},
                                    ),
                                    ("MarketVault.Treeheading.text", {"sticky": "we"}),
                                ],
                            },
                        )
                    ],
                },
            ),
        ],
    )


def configure_table_styles(style: ttk.Style, *, font_family: str | None = None) -> None:
    """Configure the shared Golden Archive table presentation."""

    _configure_table_elements(style)
    table_font = (font_family, 9) if font_family else None
    heading_font = (font_family, 9, "bold") if font_family else None
    style.configure(
        "MarketVault.Treeview",
        background=TABLE_BG,
        fieldbackground=TABLE_BG,
        foreground=TEXT_PRIMARY,
        borderwidth=0,
        relief="flat",
        rowheight=TABLE_ROWHEIGHT,
        **({"font": table_font} if table_font else {}),
    )
    style.map(
        "MarketVault.Treeview",
        background=[("selected", TABLE_SELECTION_BG)],
        foreground=[("selected", TABLE_SELECTION_TEXT)],
    )
    style.configure(
        "MarketVault.Treeview.Heading",
        background=TABLE_HEADER_BG,
        foreground=TABLE_HEADER_TEXT,
        borderwidth=1,
        relief="flat",
        padding=(8, 6),
        **({"font": heading_font} if heading_font else {}),
    )
    style.map(
        "MarketVault.Treeview.Heading",
        background=[("active", NAV_HOVER), ("pressed", NAV_SELECTED)],
        foreground=[("active", TABLE_HEADER_TEXT), ("pressed", TABLE_HEADER_TEXT)],
    )
    style.configure("MarketVault.Table.TFrame", background=TABLE_BG)
    style.configure("MarketVault.TableFooter.TFrame", background=TABLE_BG)
    style.configure(
        "MarketVault.TableInfo.TLabel",
        background=TABLE_BG,
        foreground=TEXT_SECONDARY,
        **({"font": table_font} if table_font else {}),
    )
    style.configure(
        "MarketVault.Table.TButton",
        padding=(10, 4),
        **({"font": table_font} if table_font else {}),
    )
    scrollbar_options = {
        "background": CARD_BORDER,
        "troughcolor": TABLE_BG,
        "bordercolor": TABLE_BG,
        "arrowcolor": GOLD_DARK,
        "relief": "flat",
    }
    style.configure("MarketVault.Vertical.TScrollbar", **scrollbar_options)
    style.configure("MarketVault.Horizontal.TScrollbar", **scrollbar_options)


def compact_settings_path(path: str) -> str:
    """Compact only deep presentation paths while preserving final components."""

    if not path:
        return path
    path_type = PureWindowsPath if "\\" in path else PurePosixPath
    parsed = path_type(path)
    if len(parsed.parts) <= 3:
        return str(parsed)
    separator = "\\" if path_type is PureWindowsPath else "/"
    return f"…{separator}{separator.join(parsed.parts[-2:])}"


class AmbientNumericField(tk.Canvas):
    """A bounded, deterministic binary field used only by the Home page."""

    def __init__(
        self,
        parent,
        *,
        height: int = AMBIENT_REGION_HEIGHT,
        update_interval_ms: int = AMBIENT_UPDATE_INTERVAL_MS,
        max_glyphs: int = AMBIENT_MAX_GLYPHS,
    ):
        super().__init__(
            parent,
            background=WORKSPACE_BG,
            borderwidth=0,
            height=height,
            highlightthickness=0,
        )
        self._update_interval_ms = max(100, int(update_interval_ms))
        self._max_glyphs = min(AMBIENT_MAX_GLYPHS, max(1, int(max_glyphs)))
        self._phase = 0.0
        self._running = False
        self._after_job: str | None = None
        self._resize_job: str | None = None
        self._destroyed = False
        self._glyphs: list[tuple[int, int, int, float]] = []
        fixed_font = tkfont.nametofont("TkFixedFont")
        self._glyph_font = (fixed_font.actual("family"), 8, "normal")
        self.bind("<Configure>", self._queue_grid_rebuild, add="+")

    @property
    def is_active(self) -> bool:
        return self._running

    @property
    def glyph_count(self) -> int:
        return len(self._glyphs)

    def start(self) -> None:
        if self._running or self._destroyed:
            return
        self._running = True
        if not self._glyphs:
            self._rebuild_grid()
        self._render()
        self._schedule_tick()

    def stop(self) -> None:
        self._running = False
        if self._after_job is not None:
            try:
                self.after_cancel(self._after_job)
            except tk.TclError:
                pass
            self._after_job = None

    def shutdown(self) -> None:
        self._destroyed = True
        self.stop()
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except tk.TclError:
                pass
            self._resize_job = None

    def destroy(self) -> None:
        self.shutdown()
        super().destroy()

    def _queue_grid_rebuild(self, _event=None) -> None:
        if self._destroyed:
            return
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except tk.TclError:
                pass
        self._resize_job = self.after(90, self._rebuild_grid)

    def _rebuild_grid(self) -> None:
        self._resize_job = None
        if self._destroyed:
            return
        positions = ambient_grid_positions(
            self.winfo_width(),
            self.winfo_height(),
            max_glyphs=self._max_glyphs,
        )
        self.delete("ambient-glyph")
        self._glyphs = []
        for column, row, x_position, y_position, horizontal_fraction in positions:
            item = self.create_text(
                x_position,
                y_position,
                anchor="center",
                fill=WORKSPACE_BG,
                font=self._glyph_font,
                tags=("ambient-glyph",),
                text="0",
            )
            self._glyphs.append((item, column, row, horizontal_fraction))
        self._render()

    def _schedule_tick(self) -> None:
        if self._running and self._after_job is None and not self._destroyed:
            self._after_job = self.after(self._update_interval_ms, self._tick)

    def _tick(self) -> None:
        self._after_job = None
        if not self._running or self._destroyed:
            return
        self._phase += AMBIENT_PHASE_STEP
        self._render()
        self._schedule_tick()

    def _render(self) -> None:
        if self._destroyed:
            return
        for item, column, row, horizontal_fraction in self._glyphs:
            self.itemconfigure(
                item,
                fill=ambient_fill(column, row, self._phase, horizontal_fraction),
                text=ambient_digit(column, row, self._phase),
            )


class ActivityIndicator(tk.Frame):
    """Theme-independent activity indicator with deterministic idle cleanup."""

    ACTIVE_COLOR = GOLD

    def __init__(self, parent, *, width: int = 160, height: int = 8):
        super().__init__(
            parent,
            background=CARD_BORDER,
            borderwidth=0,
            height=height + 2,
            width=width + 2,
        )
        self.pack_propagate(False)
        self._width = width
        self._height = height
        self._segment_width = 34
        self._position = 0
        self._interval = 12
        self._after_job: str | None = None
        self._running = False
        self.canvas = tk.Canvas(
            self,
            background=STATUS_BG,
            borderwidth=0,
            height=height,
            highlightthickness=0,
            width=width,
        )
        self.canvas.pack(fill="both", expand=True, padx=1, pady=1)
        self._segment = self.canvas.create_rectangle(
            0,
            0,
            0,
            height,
            fill=GOLD,
            outline="",
            state="hidden",
        )

    @property
    def is_active(self) -> bool:
        return self._running

    def start(self, interval: int = 12) -> None:
        self.stop()
        self._running = True
        self._interval = max(10, int(interval))
        self._position = 0
        self._render_segment()
        self._schedule_tick()

    def stop(self) -> None:
        self._running = False
        if self._after_job is not None:
            try:
                self.after_cancel(self._after_job)
            except tk.TclError:
                pass
            self._after_job = None
        self.canvas.coords(self._segment, 0, 0, 0, self._height)
        self.canvas.itemconfigure(self._segment, state="hidden")

    def _schedule_tick(self) -> None:
        self._after_job = self.after(self._interval, self._tick)

    def _tick(self) -> None:
        self._after_job = None
        if not self._running:
            return
        self._position += 7
        if self._position >= self._width:
            self._position = -self._segment_width
        self._render_segment()
        self._schedule_tick()

    def _render_segment(self) -> None:
        start = max(0, self._position)
        end = min(self._width, self._position + self._segment_width)
        self.canvas.coords(self._segment, start, 0, end, self._height)
        self.canvas.itemconfigure(
            self._segment,
            fill=GOLD,
            state="normal",
        )


class TableView(ttk.Frame):
    def __init__(self, parent, localization: LocalizationBindings, *, paged: bool = False):
        super().__init__(parent)
        self.localization = localization
        self.translator = localization.translator
        self.current_page = TablePage((), ())
        self._previous: Callable[[], None] | None = None
        self._next: Callable[[], None] | None = None

        self.table_border = tk.Frame(self, background=CARD_BORDER, borderwidth=0)
        self.table_border.pack(fill="both", expand=True)
        table_frame = ttk.Frame(self.table_border, style="MarketVault.Table.TFrame")
        table_frame.pack(fill="both", expand=True, padx=1, pady=1)
        self.tree = ttk.Treeview(
            table_frame,
            show="headings",
            selectmode="browse",
            style="MarketVault.Treeview",
        )
        self.tree.tag_configure("table-even", background=TABLE_BG, foreground=TEXT_PRIMARY)
        self.tree.tag_configure("table-odd", background=TABLE_ALT_BG, foreground=TEXT_PRIMARY)
        vertical = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.tree.yview,
            style="MarketVault.Vertical.TScrollbar",
        )
        horizontal = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.tree.xview,
            style="MarketVault.Horizontal.TScrollbar",
        )
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        footer = ttk.Frame(
            table_frame,
            style="MarketVault.TableFooter.TFrame",
            padding=(8, 6, 6, 5),
        )
        footer.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.info = ttk.Label(footer, style="MarketVault.TableInfo.TLabel")
        self.info.pack(side="left")
        self.next_button = ttk.Button(
            footer,
            state="disabled",
            command=self._go_next,
            style="MarketVault.Table.TButton",
        )
        self.previous_button = ttk.Button(
            footer,
            state="disabled",
            command=self._go_previous,
            style="MarketVault.Table.TButton",
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
        for index, row in enumerate(page.rows):
            row_tag = "table-even" if index % 2 == 0 else "table-odd"
            self.tree.insert("", "end", values=row, tags=(row_tag,))
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
        root.configure(background=APP_BG)
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
        shell = ttk.Frame(self.root, style="App.TFrame")
        shell.grid(row=1, column=0, sticky="nsew", padx=(14, 14), pady=(0, 8))

        self.sidebar = ttk.Frame(shell, style="Sidebar.TFrame", width=216)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Frame(shell, background=CARD_BORDER, width=1).pack(side="left", fill="y")
        workspace = ttk.Frame(shell, style="Workspace.TFrame")
        workspace.configure(padding=(12, 0, 0, 0))
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
        self.style.configure("App.TFrame", background=APP_BG)
        self.style.configure("Header.TFrame", background=HEADER_BG)
        self.style.configure("Workspace.TFrame", background=WORKSPACE_BG)
        self.style.configure("Sidebar.TFrame", background=SIDEBAR_BG)
        self.style.configure("Status.TFrame", background=STATUS_BG)
        self.style.configure("HeaderTitle.TLabel", background=HEADER_BG, foreground=TEXT_PRIMARY)
        self.style.configure("HeaderMuted.TLabel", background=HEADER_BG, foreground=TEXT_SECONDARY)
        self.style.configure("HomeSection.TLabel", background=WORKSPACE_BG, foreground=TEXT_PRIMARY)
        self.style.configure("HomeSubsection.TLabel", background=WORKSPACE_BG, foreground=TEXT_PRIMARY)
        self.style.configure("Status.TLabel", background=STATUS_BG, foreground=TEXT_PRIMARY)
        self.style.configure("StatusError.TLabel", background=STATUS_BG, foreground=ERROR)
        self.style.configure("Muted.TLabel", foreground=TEXT_SECONDARY)
        self.style.configure("Error.TLabel", foreground=ERROR)
        self.style.configure("Network.TButton", foreground=WARNING)
        self.style.configure(
            "NavigationGroup.TLabel",
            background=SIDEBAR_BG,
            foreground=TEXT_SECONDARY,
        )
        self.style.layout("Hidden.TNotebook.Tab", [])
        self.style.configure(
            "Hidden.TNotebook",
            background=WORKSPACE_BG,
            borderwidth=0,
            tabmargins=0,
        )
        self._configure_fonts()

    def _configure_fonts(self) -> None:
        family = choose_ui_font(self.translator.locale, set(tkfont.families(self.root)))
        self.style.configure("TLabel", font=(family, 9))
        self.style.configure("TButton", font=(family, 9))
        self.style.configure("TCheckbutton", font=(family, 9))
        self.style.configure("TNotebook.Tab", font=(family, 9))
        self.style.configure("TLabelframe.Label", font=(family, 9, "bold"))
        self.style.configure("HeaderTitle.TLabel", font=(family, 18, "bold"))
        self.style.configure("HomeSection.TLabel", font=(family, 12, "bold"))
        self.style.configure("HomeSubsection.TLabel", font=(family, 11, "bold"))
        self.style.configure("Metric.TLabel", font=(family, 17, "bold"))
        self.style.configure("NavigationGroup.TLabel", font=(family, 8, "bold"))
        configure_table_styles(self.style, font_family=family)
        for button in getattr(self, "navigation_buttons", {}).values():
            button.configure(font=(family, 9))
        for button in getattr(self, "home_buttons", []):
            button.configure(font=(family, 9))
        for label in getattr(self, "metric_label_widgets", []):
            label.configure(font=(family, 9))
        for value in getattr(self, "metric_value_widgets", []):
            value.configure(font=(family, 18, "bold"))

    def _build_header(self) -> None:
        header = tk.Frame(self.root, background=CARD_BORDER)
        header.grid(row=0, column=0, sticky="ew")
        content = ttk.Frame(header, padding=(18, 11), style="Header.TFrame")
        content.pack(fill="x", pady=(0, 1))
        identity = ttk.Frame(content, style="Header.TFrame")
        identity.pack(side="left")
        title = ttk.Label(identity, style="HeaderTitle.TLabel")
        title.pack(anchor="w")
        self._bind_widget(title, "header.title")
        subtitle = ttk.Label(identity, style="HeaderMuted.TLabel")
        subtitle.pack(anchor="w", pady=(2, 0))
        self._bind_widget(subtitle, "header.subtitle")
        context = ttk.Frame(content, style="Header.TFrame")
        context.pack(side="right")
        language_row = ttk.Frame(context, style="Header.TFrame")
        language_row.pack(anchor="e")
        local_mode = ttk.Label(language_row, style="HeaderMuted.TLabel")
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
        settings_context = ttk.Label(context, style="HeaderMuted.TLabel")
        settings_context.pack(anchor="e", pady=(4, 0))
        self.localization.bind(
            lambda value: settings_context.configure(text=value),
            "header.settings_path",
            settings_path=compact_settings_path(self.settings_path),
        )

    def _build_status_bar(self) -> None:
        bar = tk.Frame(self.root, background=CARD_BORDER)
        bar.grid(row=2, column=0, sticky="ew")
        content = ttk.Frame(bar, padding=(14, 6), style="Status.TFrame")
        content.pack(fill="x", pady=(1, 0))
        self.progress = ActivityIndicator(content, width=160, height=8)
        self.progress.pack(side="right")
        ttk.Label(content, textvariable=self.status_text, style="Status.TLabel").pack(
            side="left"
        )
        ttk.Label(
            content,
            textvariable=self.error_text,
            style="StatusError.TLabel",
        ).pack(side="left", padx=16)

    def _new_tab(self, page_id: PageId) -> ttk.Frame:
        tab = ttk.Frame(self.notebook, padding=12, style="Workspace.TFrame")
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
                ttk.Frame(self.sidebar, style="Sidebar.TFrame", height=10).pack(fill="x")
            for item in group.items:
                row = tk.Frame(self.sidebar, background=SIDEBAR_BG, height=38)
                row.pack(fill="x")
                row.pack_propagate(False)
                indicator = tk.Frame(row, width=4, background=SIDEBAR_BG)
                indicator.pack(side="left", fill="y")
                button = tk.Button(
                    row,
                    anchor="w",
                    background=SIDEBAR_BG,
                    activebackground=NAV_HOVER,
                    activeforeground=TEXT_PRIMARY,
                    borderwidth=0,
                    cursor="hand2",
                    foreground=TEXT_PRIMARY,
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
        self._sync_home_ambient_state()

    def _notebook_page_changed(self, _event=None) -> None:
        selected = self.notebook.select()
        page_id = self._page_ids_by_widget.get(str(selected))
        if page_id is not None:
            self.current_page_id = page_id
            self._refresh_navigation_selection()
            self._sync_home_ambient_state()

    def _sync_home_ambient_state(self) -> None:
        field = getattr(self, "ambient_field", None)
        if field is None:
            return
        if self.current_page_id == PageId.HOME:
            field.start()
        else:
            field.stop()

    def _refresh_navigation_selection(self) -> None:
        for page_id, button in self.navigation_buttons.items():
            selected = page_id == self.current_page_id
            button.configure(
                background=NAV_SELECTED if selected else SIDEBAR_BG,
                activebackground=NAV_SELECTED if selected else NAV_HOVER,
                foreground=GOLD_DARK if selected else TEXT_PRIMARY,
            )
            self.navigation_indicators[page_id].configure(
                background=GOLD if selected else SIDEBAR_BG
            )

    def _build_dashboard(self) -> None:
        tab = self._new_tab(PageId.HOME)
        self.home_buttons: list[tk.Button] = []
        hero = tk.Frame(
            tab,
            background=WORKSPACE_BG,
            height=AMBIENT_REGION_HEIGHT,
        )
        hero.pack(fill="x")
        hero.pack_propagate(False)
        self.ambient_field = AmbientNumericField(hero)
        self.ambient_field.place(x=0, y=0, relwidth=1, relheight=1)
        overview = ttk.Label(hero, style="HomeSection.TLabel")
        overview.place(x=0, rely=0.5, anchor="w")
        self._bind_widget(overview, "home.title")
        refresh = self._home_button(
            hero,
            "buttons.refresh",
            self._refresh_dashboard,
            primary=True,
        )
        refresh.place(relx=1.0, x=-8, y=12, anchor="ne")

        self.home_summary = ttk.Frame(tab, style="Workspace.TFrame")
        self.home_summary.pack(fill="x", pady=(10, 12))
        self.home_intro_card = tk.Frame(self.home_summary, background=CARD_BORDER)
        self.home_intro_card.pack(fill="x")
        intro = tk.Frame(self.home_intro_card, background=CARD_BG)
        intro.pack(fill="x", padx=1, pady=1)
        tk.Frame(intro, background=CARD_HIGHLIGHT, height=1).pack(fill="x")
        intro_body = tk.Frame(intro, background=CARD_BG, padx=14, pady=12)
        intro_body.pack(fill="x")
        self.home_message = tk.Label(
            intro_body,
            background=CARD_BG,
            foreground=TEXT_SECONDARY,
            justify="left",
            wraplength=700,
        )
        self.home_message.pack(anchor="w")
        self.home_message_binding = self.localization.bind(
            lambda value: self.home_message.configure(text=value), "home.unloaded.body"
        )
        self.home_quick_actions = tk.Frame(intro_body, background=CARD_BG)
        self.home_quick_actions.pack(anchor="w", pady=(10, 0))
        self._home_button(
            self.home_quick_actions,
            "navigation.items.historical_data",
            lambda: self.select_page(PageId.HISTORICAL_DATA),
        ).pack(side="left")
        self._home_button(
            self.home_quick_actions,
            "navigation.items.trading_calendar",
            lambda: self.select_page(PageId.TRADING_CALENDAR),
        ).pack(side="left", padx=(8, 0))

        self.dashboard_metrics = ttk.Frame(
            self.home_summary,
            style="Workspace.TFrame",
        )
        self.metric_values: dict[str, tk.StringVar] = {}
        self.metric_cards: dict[str, tk.Frame] = {}
        self.metric_label_widgets: list[tk.Label] = []
        self.metric_value_widgets: list[tk.Label] = []
        for column in range(HOME_METRIC_COLUMNS):
            self.dashboard_metrics.columnconfigure(
                column,
                weight=1,
                uniform="home_metric",
            )
        for index, (name, key) in enumerate(HOME_METRICS):
            row = index // HOME_METRIC_COLUMNS
            column = index % HOME_METRIC_COLUMNS
            panel = tk.Frame(self.dashboard_metrics, background=CARD_BORDER)
            panel.grid(
                row=row,
                column=column,
                padx=(0, 8 if column < HOME_METRIC_COLUMNS - 1 else 0),
                pady=(0, 8 if row == 0 else 0),
                sticky="nsew",
            )
            self.metric_cards[name] = panel
            inner = tk.Frame(panel, background=CARD_BG)
            inner.pack(fill="both", expand=True, padx=1, pady=1)
            tk.Frame(inner, background=CARD_HIGHLIGHT, height=1).pack(fill="x")
            tk.Frame(inner, background=GOLD_SOFT, height=1).pack(
                side="bottom",
                fill="x",
            )
            card_body = tk.Frame(inner, background=CARD_BG, padx=12, pady=10)
            card_body.pack(fill="both", expand=True)
            tk.Frame(card_body, background=GOLD, width=3).pack(side="left", fill="y")
            copy = tk.Frame(card_body, background=CARD_BG)
            copy.pack(side="left", fill="both", expand=True, padx=(10, 0))
            label = tk.Label(
                copy,
                anchor="w",
                background=CARD_BG,
                foreground=TEXT_SECONDARY,
            )
            label.pack(fill="x")
            self._bind_widget(label, key)
            self.metric_label_widgets.append(label)
            value = tk.StringVar(value="-")
            self.metric_values[name] = value
            value_label = tk.Label(
                copy,
                anchor="w",
                background=CARD_BG,
                foreground=TEXT_PRIMARY,
                textvariable=value,
            )
            value_label.pack(fill="x", pady=(3, 0))
            self.metric_value_widgets.append(value_label)
        self.home_state = HomeState.UNLOADED
        recent = ttk.Label(tab, style="HomeSubsection.TLabel")
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

    def _home_button(self, parent, key: str, command, *, primary: bool = False):
        button = tk.Button(
            parent,
            activebackground=NAV_SELECTED if primary else NAV_HOVER,
            activeforeground=GOLD_DARK if primary else TEXT_PRIMARY,
            background=GOLD_SOFT if primary else CARD_BG,
            borderwidth=0,
            command=command,
            cursor="hand2",
            foreground=GOLD_DARK if primary else TEXT_PRIMARY,
            highlightbackground=GOLD if primary else CARD_BORDER,
            highlightcolor=GOLD,
            highlightthickness=1,
            overrelief="solid",
            padx=12,
            pady=4,
            relief="flat",
            takefocus=True,
        )
        self._bind_widget(button, key)
        self.home_buttons.append(button)
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
            self.home_intro_card.pack_forget()
            self.dashboard_metrics.pack(fill="x")
            return

        self.dashboard_metrics.pack_forget()
        message_key = (
            "home.empty.body" if state == HomeState.EMPTY else "home.unloaded.body"
        )
        self.home_message_binding.update(message_key)
        self.home_intro_card.pack(fill="x")

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
        self.ambient_field.shutdown()
        self.progress.stop()
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
