from __future__ import annotations

import logging
from pathlib import Path

import pytest


pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QQmlApplicationEngine

from market_vault.application import ApplicationContext
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore


class _Runner:
    def __init__(self) -> None:
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def test_qml_session_wires_all_pages_to_one_application_context(qt_app, tmp_path):
    backend = object()
    runner = _Runner()
    context = ApplicationContext(
        settings_path=(tmp_path / "config" / "settings.yaml").resolve(),
        settings=object(),
        backend=backend,
        task_runner=runner,
        logger=logging.getLogger("market-vault-qml-bootstrap-test"),
    )
    engine = QQmlApplicationEngine()
    session = create_qml_application_session(
        context,
        engine,
        preference_store=DesktopPreferenceStore(root=tmp_path / "preferences"),
    )

    session.validate_wiring()
    assert session.runtime.application_context is context
    assert session.runtime.backend_if_initialized is backend
    assert session.runtime.settings_path == context.settings_path
    assert session.dashboard._runtime is session.runtime
    assert all(controller._runtime is session.runtime for controller in session.controllers)
    assert engine._market_vault_application_session is session

    assert session.shutdown() is True
    assert session.shutdown() is True
    assert context.closed is True
    assert runner.close_count == 1
