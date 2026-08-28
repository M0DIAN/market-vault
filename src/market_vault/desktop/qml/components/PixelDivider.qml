import QtQuick
import "../theme" as Theme

Item {
    id: root
    implicitWidth: 160
    implicitHeight: 2
    property color lineColor: Theme.PixelTheme.goldMid
    property color accentColor: Theme.PixelTheme.gold
    property int accentWidth: 34

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: 1
        color: root.lineColor
    }
    Rectangle {
        id: accent
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(root.accentWidth, root.width)
        height: 2
        color: root.accentColor
    }
    Rectangle {
        anchors.left: accent.left
        anchors.top: accent.top
        width: Math.min(8, accent.width)
        height: 1
        color: Theme.PixelTheme.goldLight
    }
}
