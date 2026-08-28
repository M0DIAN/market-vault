import QtQuick
import QtQuick.Controls
import "../theme" as Theme

ScrollBar {
    id: control
    policy: ScrollBar.AsNeeded
    implicitWidth: 10
    implicitHeight: 10
    padding: 2
    contentItem: Rectangle {
        implicitWidth: 6
        implicitHeight: 42
        color: control.pressed ? Theme.PixelTheme.goldDark
            : (control.hovered ? Theme.PixelTheme.gold : Theme.PixelTheme.line)
        opacity: control.size < 1 ? 1 : 0
    }
    background: Rectangle {
        color: Theme.PixelTheme.surfaceMuted
        border.color: Theme.PixelTheme.lineSoft
        border.width: 1
    }
}
