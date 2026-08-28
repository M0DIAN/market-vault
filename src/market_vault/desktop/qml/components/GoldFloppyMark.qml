import QtQuick
import "../theme" as Theme

Item {
    id: root
    implicitWidth: 32
    implicitHeight: 32
    property bool interactive: true

    Rectangle {
        anchors.fill: parent
        color: Theme.PixelTheme.goldDark
    }
    Rectangle {
        anchors.fill: parent
        anchors.margins: Theme.PixelTheme.pixelUnit
        color: Theme.PixelTheme.goldMid
    }
    Rectangle {
        x: Theme.PixelTheme.pixelUnit
        y: Theme.PixelTheme.pixelUnit
        width: root.width - Theme.PixelTheme.pixelUnit * 2
        height: Theme.PixelTheme.pixelUnit * 2
        color: Theme.PixelTheme.goldLight
    }
    Rectangle {
        x: root.width - Theme.PixelTheme.pixelUnit * 2
        y: Theme.PixelTheme.pixelUnit * 2
        width: Theme.PixelTheme.pixelUnit
        height: root.height - Theme.PixelTheme.pixelUnit * 4
        color: Theme.PixelTheme.goldDark
    }
    Rectangle {
        x: root.width * 0.22
        y: Theme.PixelTheme.pixelUnit
        width: root.width * 0.56
        height: root.height * 0.34
        color: Theme.PixelTheme.goldPale
        border.color: Theme.PixelTheme.goldDark
        border.width: 1
    }
    Rectangle {
        x: root.width * 0.6
        y: Theme.PixelTheme.pixelUnit * 2
        width: root.width * 0.1
        height: root.height * 0.24
        color: Theme.PixelTheme.ink
    }
    Rectangle {
        x: root.width * 0.18
        y: root.height * 0.54
        width: root.width * 0.64
        height: root.height * 0.34
        color: Theme.PixelTheme.surfaceRaised
        border.color: Theme.PixelTheme.goldDark
        border.width: 1
    }
    Rectangle {
        x: root.width * 0.18 + 2
        y: root.height * 0.54 + 2
        width: root.width * 0.64 - 4
        height: 2
        color: Theme.PixelTheme.goldLight
    }
    Rectangle {
        x: Theme.PixelTheme.pixelUnit
        y: Theme.PixelTheme.pixelUnit
        width: root.width - Theme.PixelTheme.pixelUnit * 2
        height: 1
        color: Theme.PixelTheme.goldLight
    }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.surface; anchors.left: parent.left; anchors.top: parent.top }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.surface; anchors.right: parent.right; anchors.top: parent.top }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.surface; anchors.left: parent.left; anchors.bottom: parent.bottom }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.surface; anchors.right: parent.right; anchors.bottom: parent.bottom }

    Rectangle {
        id: specular
        x: Theme.PixelTheme.pixelUnit * 2
        y: Theme.PixelTheme.pixelUnit
        width: Theme.PixelTheme.pixelUnit * 3
        height: Theme.PixelTheme.pixelUnit
        color: Theme.PixelTheme.goldHighlight
        opacity: hover.hovered ? 0.9 : 0.35
        Behavior on opacity { NumberAnimation { duration: Theme.PixelTheme.motionSlow } }
    }
    HoverHandler { id: hover; enabled: root.interactive }
}
