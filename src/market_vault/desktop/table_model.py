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

        # Keep the canary startup lazy: importing Console models also imports the
        # Console package, so type validation happens only when data is supplied.
        from market_vault.console.models import TablePage as ConsoleTablePage

        if not isinstance(page, ConsoleTablePage):
            raise TypeError("page must be a market_vault.console.models.TablePage")
        expected_columns = len(page.columns)
        for row_index, row in enumerate(page.rows):
            if len(row) != expected_columns:
                raise ValueError(
                    "TablePage row length does not match columns: "
                    f"row={row_index}, expected={expected_columns}, actual={len(row)}"
                )

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
