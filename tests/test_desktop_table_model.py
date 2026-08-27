from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest


pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QModelIndex, Qt

from market_vault.console.models import TablePage
from market_vault.desktop.table_model import QtTableModel
from market_vault.desktop.table_model import validate_table_page


@pytest.fixture(scope="module")
def qt_app():
    application = QCoreApplication.instance() or QCoreApplication([])
    yield application


def _page(
    *,
    columns=("run_id", "status"),
    rows=(("run-1", "SUCCESS"),),
    page=1,
    page_size=20,
    total_rows=None,
):
    return TablePage(
        columns=columns,
        rows=rows,
        page=page,
        page_size=page_size,
        total_rows=len(rows) if total_rows is None else total_rows,
    )


def test_empty_table_page_is_supported(qt_app):
    model = QtTableModel()
    model.set_page(TablePage(columns=(), rows=(), total_rows=0))

    assert model.rowCount() == 0
    assert model.columnCount() == 0
    assert model.page == 1
    assert model.pageSize == 100
    assert model.totalRows == 0
    assert model.totalPages == 1
    assert model.hasPrevious is False
    assert model.hasNext is False


def test_display_role_headers_and_dynamic_shape(qt_app):
    model = QtTableModel()
    model.set_page(
        _page(
            columns=("run_id", "status", "rows"),
            rows=(("run-1", "SUCCESS", "5"), ("run-2", "FAILED", "0")),
        )
    )

    assert model.rowCount() == 2
    assert model.columnCount() == 3
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "run-1"
    assert model.data(model.index(1, 2), Qt.ItemDataRole.DisplayRole) == "0"
    assert model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole) is None
    assert model.data(QModelIndex(), Qt.ItemDataRole.DisplayRole) is None
    assert model.headerData(1, Qt.Orientation.Horizontal) == "status"
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(99, Qt.Orientation.Horizontal) is None
    assert model.roleNames() == {int(Qt.ItemDataRole.DisplayRole): b"display"}


def test_set_page_replaces_data_with_one_reset_and_metadata_notification(qt_app):
    model = QtTableModel()
    resets = []
    metadata = []
    model.modelReset.connect(lambda: resets.append(model.rowCount()))
    model.metadataChanged.connect(lambda: metadata.append(model.totalRows))

    model.set_page(_page(rows=(("run-1", "SUCCESS"),)))
    model.set_page(
        _page(
            rows=(("run-2", "FAILED"), ("run-3", "SUCCESS")),
            page=2,
            page_size=2,
            total_rows=5,
        )
    )

    assert resets == [1, 2]
    assert metadata == [1, 5]
    assert model.data(model.index(0, 0)) == "run-2"
    assert model.page == 2
    assert model.pageSize == 2
    assert model.totalRows == 5
    assert model.totalPages == 3
    assert model.hasPrevious is True
    assert model.hasNext is True


def test_malformed_rows_fail_before_model_reset(qt_app):
    model = QtTableModel()
    model.set_page(_page())
    resets = []
    model.modelReset.connect(lambda: resets.append(True))

    malformed = TablePage(
        columns=("run_id", "status"),
        rows=(("run-2",),),
        total_rows=1,
    )
    with pytest.raises(ValueError, match="row length does not match columns"):
        model.set_page(malformed)

    assert resets == []
    assert model.data(model.index(0, 0)) == "run-1"


def test_non_table_page_fails_closed(qt_app):
    model = QtTableModel()
    with pytest.raises(TypeError, match="TablePage"):
        model.set_page(object())


def test_worker_thread_model_mutation_is_rejected(qt_app):
    model = QtTableModel()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(model.set_page, _page())
        with pytest.raises(RuntimeError, match="owning thread"):
            future.result(timeout=5)

    assert model.rowCount() == 0


@pytest.mark.parametrize(
    "page",
    [
        TablePage(columns=("x",), rows=(("1",),), page=0, total_rows=1),
        TablePage(columns=("x",), rows=(("1",),), page_size=0, total_rows=1),
        TablePage(columns=("x",), rows=(("1",),), page_size=1001, total_rows=1),
        TablePage(columns=("x",), rows=(("1",),), total_rows=0),
        TablePage(columns=("x",), rows=(("1",),), page=2, total_rows=1),
    ],
)
def test_complete_table_metadata_validation_fails_closed(page):
    with pytest.raises(ValueError):
        validate_table_page(page)
