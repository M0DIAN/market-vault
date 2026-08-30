"""Minimal QObject bridge for the QML-1 desktop canary."""

from PySide6.QtCore import Property, QObject, Signal, Slot


class DesktopBridge(QObject):
    """Expose one observable, non-business state transition to QML."""

    statusChanged = Signal()

    def __init__(
        self,
        application_icon_url: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._application_icon_url = application_icon_url
        self._status = "QML ready"

    @Property(str, constant=True)
    def applicationIconUrl(self) -> str:
        return self._application_icon_url

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
