from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = ROOT / "src" / "market_vault" / "desktop" / "qml"
HOME_QML = QML_ROOT / "pages" / "HomePage.qml"
APPLICATION_ICON = ROOT / "assets" / "windows" / "market-vault.ico"


def test_home_uses_the_application_icon_url_and_scoped_metric_glyph_size():
    home = HOME_QML.read_text(encoding="utf-8")
    pixel_glyph = (QML_ROOT / "components" / "PixelGlyph.qml").read_text(
        encoding="utf-8"
    )
    sidebar = (QML_ROOT / "components" / "Sidebar.qml").read_text(
        encoding="utf-8"
    )

    assert 'objectName: "homeApplicationIcon"' in home
    assert "source: home.desktop.applicationIconUrl" in home
    assert "fillMode: Image.PreserveAspectFit" in home
    assert "smooth: false" in home
    assert "mipmap: false" in home
    assert 'objectName: "homeApplicationIconFallback"' in home
    assert "applicationIcon.status === Image.Ready" in home
    assert "visible: !applicationIconContainer.applicationIconReady" in home
    assert "Layout.preferredWidth: 42" in home
    assert "Layout.preferredHeight: 42" in home
    assert 'objectName: "homeMetricGlyph_" + modelData.objectKey' in home
    assert "Layout.preferredWidth: 24" in home
    assert "Layout.preferredHeight: 24" in home
    assert "Layout.preferredHeight: 72" in home
    assert "Math.floor" not in home
    assert "implicitWidth: 18" in pixel_glyph
    assert "implicitHeight: 18" in pixel_glyph
    assert "Layout.preferredWidth: 24" in sidebar
    assert "Layout.preferredHeight: 24" in sidebar


@pytest.mark.parametrize("scale_factor", ("1", "1.25", "1.5", "2"))
def test_home_icon_and_metric_geometry_across_dpi_language_and_minimum_window(
    tmp_path: Path,
    scale_factor: str,
):
    pytest.importorskip("PySide6")
    script = f'''
import json
import logging
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from market_vault.application import ApplicationContext
from market_vault.desktop.bootstrap import create_qml_application_session
from market_vault.desktop.preferences import DesktopPreferenceStore


QQuickStyle.setStyle("Basic")
app = QGuiApplication([])
engine = QQmlApplicationEngine()
context = ApplicationContext(
    settings_path=Path({str(tmp_path / "config" / "settings.yaml")!r}),
    settings=object(),
    logger=logging.getLogger("market-vault-home-visual-test"),
    backend_factory=lambda settings: (_ for _ in ()).throw(
        AssertionError("home visual test initialized backend")
    ),
    runner_factory=lambda: (_ for _ in ()).throw(
        AssertionError("home visual test initialized runner")
    ),
)
icon_url = QUrl.fromLocalFile({str(APPLICATION_ICON)!r}).toString()
session = create_qml_application_session(
    context,
    engine,
    application_icon_url=icon_url,
    preference_store=DesktopPreferenceStore(
        root=Path({str(tmp_path / "preferences")!r})
    ),
)
engine.load(QUrl.fromLocalFile({str(QML_ROOT / "Main.qml")!r}))
if not engine.rootObjects():
    raise RuntimeError("Main.qml home visual fixture did not load")
root = engine.rootObjects()[0]
root.setProperty("width", 1000)
root.setProperty("height", 650)


def settle():
    for _ in range(5):
        app.processEvents()
    QTest.qWait(120)
    for _ in range(5):
        app.processEvents()


def number(item, name):
    return float(item.property(name))


def find_visual(window, object_name):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == object_name:
            return item
        pending.extend(item.childItems())
    raise RuntimeError(f"missing visual item: {{object_name}}")


def rect_in(item, ancestor):
    point = item.mapToItem(ancestor, QPointF(0, 0))
    return {{
        "left": point.x(),
        "top": point.y(),
        "right": point.x() + number(item, "width"),
        "bottom": point.y() + number(item, "height"),
        "width": number(item, "width"),
        "height": number(item, "height"),
    }}


evidence = []
metric_keys = (
    "symbols",
    "snapshots",
    "latestRows",
    "completedDates",
    "incompleteDates",
    "latestTradeDate",
)
for language in ("zh-CN", "en"):
    session.i18n.setLanguage(language)
    settle()
    home = find_visual(root, "homePage")
    image = find_visual(root, "homeApplicationIcon")
    fallback = find_visual(root, "homeApplicationIconFallback")
    container = find_visual(root, "homeApplicationIconContainer")
    metrics = []
    cards = []
    for key in metric_keys:
        glyph = find_visual(root, f"homeMetricGlyph_{{key}}")
        card = find_visual(root, f"homeMetricCard_{{key}}")
        glyph_rect = rect_in(glyph, card)
        card_rect = rect_in(card, home)
        metrics.append({{
            "width": number(glyph, "width"),
            "height": number(glyph, "height"),
            "pixel_unit": math.floor(
                min(number(glyph, "width"), number(glyph, "height")) / 12
            ),
            "vertical_center_delta": abs(
                (glyph_rect["top"] + glyph_rect["bottom"]) / 2
                - number(card, "height") / 2
            ),
            "contained": (
                glyph_rect["left"] >= 0
                and glyph_rect["top"] >= 0
                and glyph_rect["right"] <= number(card, "width")
                and glyph_rect["bottom"] <= number(card, "height")
            ),
        }})
        cards.append(card_rect)
    evidence.append({{
        "language": language,
        "root_width": number(root, "width"),
        "root_height": number(root, "height"),
        "icon_source": image.property("source").toString(),
        "icon_ready": bool(container.property("applicationIconReady")),
        "icon_visible": bool(image.property("visible")),
        "fallback_visible": bool(fallback.property("visible")),
        "icon_width": number(image, "width"),
        "icon_height": number(image, "height"),
        "painted_width": number(image, "paintedWidth"),
        "painted_height": number(image, "paintedHeight"),
        "container_width": number(container, "width"),
        "container_height": number(container, "height"),
        "metrics": metrics,
        "cards": cards,
        "home_width": number(home, "width"),
        "home_height": number(home, "height"),
    }})

assert session.shutdown()
print(json.dumps(evidence))
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QSG_RHI_BACKEND"] = "software"
    env["QT_SCALE_FACTOR"] = scale_factor
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
    output = json.loads(result.stdout)
    assert len(output) == 2
    expected_url = pytest.importorskip("PySide6.QtCore").QUrl.fromLocalFile(
        str(APPLICATION_ICON)
    ).toString()
    for language in output:
        assert language["root_width"] == pytest.approx(1000)
        assert language["root_height"] == pytest.approx(650)
        assert language["icon_source"] == expected_url
        assert language["icon_ready"] is True
        assert language["icon_visible"] is True
        assert language["fallback_visible"] is False
        assert language["container_width"] == pytest.approx(42)
        assert language["container_height"] == pytest.approx(42)
        assert language["icon_width"] == pytest.approx(42)
        assert language["icon_height"] == pytest.approx(42)
        assert language["painted_width"] > 0
        assert language["painted_height"] > 0
        assert language["painted_width"] == pytest.approx(
            language["painted_height"]
        )
        assert len(language["metrics"]) == 6
        assert len(language["cards"]) == 6
        for metric in language["metrics"]:
            assert metric["width"] == pytest.approx(24)
            assert metric["height"] == pytest.approx(24)
            assert metric["pixel_unit"] == 2
            assert metric["vertical_center_delta"] <= 1
            assert metric["contained"] is True
        xs = sorted({round(card["left"], 2) for card in language["cards"]})
        ys = sorted({round(card["top"], 2) for card in language["cards"]})
        assert len(xs) == 3
        assert len(ys) == 2
        for card in language["cards"]:
            assert card["height"] == pytest.approx(72)
            assert card["left"] >= 0
            assert card["top"] >= 0
            assert card["right"] <= language["home_width"] + 0.01
            assert card["bottom"] <= language["home_height"] + 0.01


def test_home_visual_polish_does_not_duplicate_or_modify_icon_assets():
    icons = sorted((ROOT / "assets" / "windows").glob("*.ico"))

    assert icons == [APPLICATION_ICON]
    assert APPLICATION_ICON.is_file()
