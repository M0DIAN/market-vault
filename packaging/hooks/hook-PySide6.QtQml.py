"""Collect the production QML import closure, not every installed QML module."""

from pathlib import Path, PurePath

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

_QML_MODULES = (
    "QtQml",
    "QtQml/Models",
    "QtQml/WorkerScript",
    "QtQuick",
    "QtQuick/Controls",
    "QtQuick/Controls/Basic",
    "QtQuick/Controls/Basic/impl",
    "QtQuick/Controls/impl",
    "QtQuick/Dialogs",
    "QtQuick/Dialogs/quickimpl",
    "QtQuick/Effects",
    "QtQuick/Layouts",
    "QtQuick/Shapes",
    "QtQuick/Templates",
    "QtQuick/Window",
)

qml_source_root = Path(pyside6_library_info.location["QmlImportsPath"]).resolve()
qml_destination_root = PurePath(pyside6_library_info.qt_rel_dir) / "qml"
_EXCLUDED_QML_PARTS = {("QtQuick", "Controls", "designer")}


def _destination(source: Path) -> str:
    relative = source.relative_to(qml_source_root)
    if source.is_file():
        relative = relative.parent
    return str(qml_destination_root / relative)


def _is_runtime_file(source: Path) -> bool:
    relative_parts = source.relative_to(qml_source_root).parts
    return not any(
        relative_parts[: len(excluded)] == excluded
        for excluded in _EXCLUDED_QML_PARTS
    )


for relative_module in _QML_MODULES:
    qmldir = qml_source_root / relative_module / "qmldir"
    if not qmldir.is_file():
        raise RuntimeError(f"Required QML module is unavailable: {relative_module}")
    module_binaries, module_datas = pyside6_library_info._process_qml_plugin(qmldir)
    binaries += [
        (str(source), _destination(source))
        for source in module_binaries
        if _is_runtime_file(source)
    ]
    datas += [
        (str(source), _destination(source))
        for source in module_datas
        if _is_runtime_file(source)
    ]
