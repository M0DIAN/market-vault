"""Minimal QObject bridge for the QML-1 desktop canary."""

from PySide6.QtCore import Property, QObject, Signal, Slot


class DesktopBridge(QObject):
    """Expose one observable, non-business state transition to QML."""

    statusChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._status = "QML ready"

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Slot()
    def ping(self) -> None:
        next_status = "Python bridge OK"
        if self._status == next_status:
            return
        self._status = next_status
        self.statusChanged.emit()
