import QtQuick
import QtQuick.Controls
import "../theme" as Theme

TextField {
    id: control
    implicitHeight: Theme.PixelTheme.controlHeight
    leftPadding: 10
    rightPadding: 10
    selectByMouse: true
    activeFocusOnTab: true
    color: Theme.PixelTheme.ink
    placeholderTextColor: Theme.PixelTheme.inkFaint
    selectionColor: Theme.PixelTheme.goldLight
    selectedTextColor: Theme.PixelTheme.ink
    font.family: Theme.PixelTheme.uiFont
    font.pixelSize: Theme.PixelTheme.fontMd
    opacity: enabled ? 1 : Theme.PixelTheme.disabledOpacity
    background: Item {
        Rectangle { anchors.fill: parent; color: control.activeFocus ? Theme.PixelTheme.goldDark : Theme.PixelTheme.line }
        Rectangle {
            anchors.fill: parent
            anchors.margins: control.activeFocus ? 3 : 1
            color: Theme.PixelTheme.surfaceRaised
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: control.activeFocus ? 4 : 2
            anchors.rightMargin: control.activeFocus ? 4 : 2
            anchors.topMargin: control.activeFocus ? 4 : 2
            height: 1
            color: Theme.PixelTheme.goldLight
        }
        Rectangle { anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.right: parent.right; anchors.margins: control.activeFocus ? 4 : 2; height: 1; color: Theme.PixelTheme.goldDark }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.top: parent.top }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.top: parent.top }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.bottom: parent.bottom }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.bottom: parent.bottom }
    }
}
