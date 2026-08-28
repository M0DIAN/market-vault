import QtQuick
import QtQuick.Controls
import "../theme" as Theme

Item {
    id: root
    property alias text: label.text
    property color accentColor: Theme.PixelTheme.gold
    implicitWidth: label.implicitWidth + 20
    implicitHeight: 28
    Rectangle { anchors.fill: parent; color: Theme.PixelTheme.line }
    Rectangle { anchors.fill: parent; anchors.margins: 1; color: Theme.PixelTheme.surfaceRaised }
    Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 3; color: root.accentColor }
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 2; height: 1; color: Theme.PixelTheme.goldLight }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.top: parent.top }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.top: parent.top }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.bottom: parent.bottom }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.bottom: parent.bottom }
    Label {
        id: label
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 7
        color: Theme.PixelTheme.ink
        font.family: Theme.PixelTheme.uiFont
        font.pixelSize: Theme.PixelTheme.fontSm
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
