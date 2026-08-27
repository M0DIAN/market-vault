"""Qt presentation adapter for immutable Console ``TablePage`` snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    Property,
    Qt,
    QThread,
    Signal,
)


if TYPE_CHECKING:
    from market_vault.console.models import TablePage


def validate_table_page(page: TablePage) -> TablePage:
    """Validate a complete immutable table snapshot without changing Qt state."""

    # Keep desktop startup lazy by importing Console models only when data arrives.
    from market_vault.console.models import TablePage as ConsoleTablePage

    if not isinstance(page, ConsoleTablePage):
        raise TypeError("page must be a market_vault.console.models.TablePage")
    if not isinstance(page.columns, tuple) or not all(
        isinstance(column, str) for column in page.columns
    ):
        raise TypeError("TablePage columns must be a tuple of strings")
    if not isinstance(page.rows, tuple):
        raise TypeError("TablePage rows must be a tuple")
    expected_columns = len(page.columns)
    for row_index, row in enumerate(page.rows):
        if not isinstance(row, tuple):
            raise TypeError(f"TablePage row {row_index} must be a tuple")
        if len(row) != expected_columns:
            raise ValueError(
                "TablePage row length does not match columns: "
                f"row={row_index}, expected={expected_columns}, actual={len(row)}"
            )
        if not all(isinstance(value, str) for value in row):
            raise TypeError(f"TablePage row {row_index} values must be strings")
    for field_name, value, minimum in (
        ("page", page.page, 1),
        ("page_size", page.page_size, 1),
        ("total_rows", page.total_rows, 0),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"TablePage {field_name} must be an integer >= {minimum}")
    if page.page_size > 1000:
        raise ValueError("TablePage page_size must be <= 1000")
    if len(page.rows) > page.page_size:
        raise ValueError("TablePage rows exceed page_size")
    if page.total_rows < len(page.rows):
        raise ValueError("TablePage total_rows is smaller than the loaded rows")
    if page.page > page.total_pages:
        raise ValueError("TablePage page exceeds total_pages")
    return page


class QtTableModel(QAbstractTableModel):
    """Expose one immutable ``TablePage`` through Qt's table model contract."""

    metadataChanged = Signal()

    def __init__(self, *, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._page: TablePage | None = None

    def _assert_model_thread(self) -> None:
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Qt table model must be updated on its owning thread.")

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or self._page is None:
            return 0
        return len(self._page.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or self._page is None:
            return 0
        return len(self._page.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if (
            role != Qt.ItemDataRole.DisplayRole
            or not index.isValid()
            or self._page is None
            or not 0 <= index.row() < len(self._page.rows)
            or not 0 <= index.column() < len(self._page.columns)
        ):
            return None
        return self._page.rows[index.row()][index.column()]

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if (
            role != Qt.ItemDataRole.DisplayRole
            or orientation != Qt.Orientation.Horizontal
            or self._page is None
            or not 0 <= section < len(self._page.columns)
        ):
            return None
        return self._page.columns[section]

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return {int(Qt.ItemDataRole.DisplayRole): b"display"}

    def set_page(self, page: TablePage) -> None:
        """Replace the current immutable page using one Qt model reset."""

        self._assert_model_thread()

        validate_table_page(page)

        self.beginResetModel()
        try:
            self._page = page
        finally:
            self.endResetModel()
        self.metadataChanged.emit()

    @Property(int, notify=metadataChanged)
    def page(self) -> int:
        return self._page.page if self._page is not None else 1

    @Property(int, notify=metadataChanged)
    def pageSize(self) -> int:  # noqa: N802
        return self._page.page_size if self._page is not None else 0

    @Property(int, notify=metadataChanged)
    def totalRows(self) -> int:  # noqa: N802
        return self._page.total_rows if self._page is not None else 0

    @Property(int, notify=metadataChanged)
    def totalPages(self) -> int:  # noqa: N802
        return self._page.total_pages if self._page is not None else 1

    @Property(bool, notify=metadataChanged)
    def hasPrevious(self) -> bool:  # noqa: N802
        return self._page.has_previous if self._page is not None else False

    @Property(bool, notify=metadataChanged)
    def hasNext(self) -> bool:  # noqa: N802
        return self._page.has_next if self._page is not None else False
