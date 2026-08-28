from __future__ import annotations

from concurrent.futures import Future
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication
from PySide6.QtQml import QQmlApplicationEngine

from market_vault.application import ApplicationContext, build_application_context
from market_vault.console.models import DashboardSnapshot, TablePage
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.dashboard import DASHBOARD_METRIC_NAMES
from market_vault.desktop.preferences import DesktopPreferenceStore


ROOT = Path(__file__).resolve().parents[1]


class _Runner:
    def __init__(self) -> None:
        self.close_count = 0
        self.submit_count = 0

    def submit(self, name, operation):
        self.submit_count += 1
        future = Future()
        try:
            future.set_result(operation())
        except Exception as exc:
            future.set_exception(exc)
        return future

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
        logger=logging.getLogger("market-vault-qml-bootstrap-test"),
        backend_factory=lambda settings: backend,
        runner_factory=lambda: runner,
    )
    engine = QQmlApplicationEngine()
    session = create_qml_application_session(
        context,
        engine,
        preference_store=DesktopPreferenceStore(root=tmp_path / "preferences"),
    )

    session.validate_wiring()
    assert session.runtime.application_context is context
    assert session.runtime.backend_if_initialized is None
    assert session.runtime.task_runner_if_initialized is None
    assert context.backend_if_initialized is None
    assert context.task_runner_if_initialized is None
    assert session.runtime.settings_path == context.settings_path
    assert session.dashboard._runtime is session.runtime
    assert all(controller._runtime is session.runtime for controller in session.controllers)
    assert engine._market_vault_application_session is session

    assert session.shutdown() is True
    assert session.shutdown() is True
    assert context.closed is True
    assert runner.close_count == 0


def test_first_business_operation_initializes_and_reuses_shared_dependencies(
    qt_app, tmp_path
):
    backend_calls = []
    runner_calls = []
    runner = _Runner()

    class Backend:
        def dashboard(self):
            backend_calls.append("dashboard")
            return DashboardSnapshot(
                status="SUCCESS",
                metrics={name: "0" for name in DASHBOARD_METRIC_NAMES},
                recent_runs=TablePage(columns=(), rows=()),
            )

    backend = Backend()
    context = ApplicationContext(
        settings_path=(tmp_path / "config" / "settings.yaml").resolve(),
        settings=object(),
        logger=logging.getLogger("market-vault-qml-operation-test"),
        backend_factory=lambda settings: backend_calls.append("factory") or backend,
        runner_factory=lambda: runner_calls.append("factory") or runner,
    )
    engine = QQmlApplicationEngine()
    session = create_qml_application_session(
        context,
        engine,
        preference_store=DesktopPreferenceStore(root=tmp_path / "preferences"),
    )

    assert session.dashboard.refresh() is True
    session.runtime._poll()
    session.validate_wiring()
    assert session.runtime.backend_if_initialized is backend
    assert context.backend_if_initialized is backend
    assert session.runtime.task_runner_if_initialized is runner
    assert context.task_runner_if_initialized is runner

    assert session.dashboard.refresh() is True
    session.runtime._poll()
    assert backend_calls == ["factory", "dashboard", "dashboard"]
    assert runner_calls == ["factory"]
    assert runner.submit_count == 2

    assert session.shutdown() is True
    assert session.shutdown() is True
    assert runner.close_count == 1


def test_first_real_local_dashboard_operation_uses_only_sandbox_dependencies(
    qt_app, tmp_path
):
    sandbox = tmp_path / "real local operation"
    settings = sandbox / "config" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        """
storage:
  root_dir: ./data
  catalog_path: ./catalog/market_vault.duckdb
  manifest_dir: ./manifests
  report_dir: ./reports/data_quality
""".lstrip(),
        encoding="utf-8",
    )
    context = build_application_context(settings)
    engine = QQmlApplicationEngine()
    session = create_qml_application_session(
        context,
        engine,
        preference_store=DesktopPreferenceStore(root=sandbox / "preferences"),
    )

    assert context.backend_if_initialized is None
    assert context.task_runner_if_initialized is None
    assert not (sandbox / "catalog").exists()
    assert session.dashboard.refresh() is True
    deadline = time.monotonic() + 10
    while session.runtime.busy:
        qt_app.processEvents()
        if time.monotonic() >= deadline:
            raise AssertionError("Dashboard operation did not finish")
        time.sleep(0.005)
    qt_app.processEvents()

    backend = context.backend_if_initialized
    runner = context.task_runner_if_initialized
    assert backend is not None
    assert runner is not None
    assert session.runtime.backend_if_initialized is backend
    assert session.runtime.task_runner_if_initialized is runner
    assert session.dashboard.status == "EMPTY"
    assert backend.vault.settings.data_root == (sandbox / "data").resolve()
    assert backend.vault.settings.catalog_path == (
        sandbox / "catalog" / "market_vault.duckdb"
    ).resolve()
    assert backend.vault.settings.manifest_dir == (sandbox / "manifests").resolve()
    assert backend.vault.settings.report_dir == (
        sandbox / "reports" / "data_quality"
    ).resolve()
    session.validate_wiring()

    assert session.dashboard.refresh() is True
    deadline = time.monotonic() + 10
    while session.runtime.busy:
        qt_app.processEvents()
        if time.monotonic() >= deadline:
            raise AssertionError("Second dashboard operation did not finish")
        time.sleep(0.005)
    qt_app.processEvents()
    assert context.backend_if_initialized is backend
    assert context.task_runner_if_initialized is runner
    assert session.shutdown() is True


def test_qml_startup_navigation_and_language_switch_are_storage_side_effect_free(
    tmp_path,
):
    sandbox = tmp_path / "qml startup sandbox"
    settings = sandbox / "config" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        """
storage:
  root_dir: ./data
  catalog_path: ./catalog/market_vault.duckdb
  manifest_dir: ./manifests
  report_dir: ./reports/data_quality
""".lstrip(),
        encoding="utf-8",
    )
    script = f"""
import json
from pathlib import Path
import sys
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from market_vault.application import build_application_context
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore
from market_vault.desktop.shell import PAGE_IDS

settings = Path({str(settings)!r})
sandbox = Path({str(sandbox)!r})
calls = []
context = build_application_context(
    settings,
    backend_factory=lambda value: calls.append('backend'),
    runner_factory=lambda: calls.append('runner'),
)
QQuickStyle.setStyle('Basic')
app = QGuiApplication([])
engine = QQmlApplicationEngine()
session = create_qml_application_session(
    context,
    engine,
    preference_store=DesktopPreferenceStore(root=sandbox / 'preferences'),
)
engine.load(QUrl.fromLocalFile({str(ROOT / 'src' / 'market_vault' / 'desktop' / 'qml' / 'Main.qml')!r}))
assert engine.rootObjects()
session.validate_wiring()
for page_id in PAGE_IDS:
    assert session.shell.selectPage(page_id)
assert session.i18n.setLanguage('zh-CN')
assert session.i18n.setLanguage('en')
app.processEvents()
storage_paths = [sandbox / name for name in ('data', 'catalog', 'manifests', 'reports')]
evidence = {{
    'calls': calls,
    'backend_initialized': context.backend_if_initialized is not None,
    'runner_initialized': context.task_runner_if_initialized is not None,
    'runtime_backend_initialized': session.runtime.backend_if_initialized is not None,
    'runtime_runner_initialized': session.runtime.task_runner_if_initialized is not None,
    'backend_module_imported': 'market_vault.console.backend' in sys.modules,
    'api_module_imported': 'market_vault.api' in sys.modules,
    'storage_paths_created': [str(path) for path in storage_paths if path.exists()],
    'page': session.shell.currentPage,
    'language': session.i18n.language,
}}
assert session.shutdown()
evidence['closed'] = context.closed
print(json.dumps(evidence))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip()) == {
        "calls": [],
        "backend_initialized": False,
        "runner_initialized": False,
        "runtime_backend_initialized": False,
        "runtime_runner_initialized": False,
        "backend_module_imported": False,
        "api_module_imported": False,
        "storage_paths_created": [],
        "page": "storage_cleanup",
        "language": "en",
        "closed": True,
    }
