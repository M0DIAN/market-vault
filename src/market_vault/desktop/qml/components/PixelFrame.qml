import QtQuick
import "../theme" as Theme

Item {
    id: root
    default property alias contentData: content.data
    property color fillColor: Theme.PixelTheme.surfaceRaised
    property color borderColor: Theme.PixelTheme.line
    property color accentColor: Theme.PixelTheme.gold
    property bool accented: false
    property bool metallic: true
    property int padding: Theme.PixelTheme.panelPadding

    Rectangle { anchors.fill: parent; color: root.metallic ? Theme.PixelTheme.goldDark : root.borderColor }
    Rectangle { anchors.fill: parent; anchors.margins: 1; color: root.borderColor }
    Rectangle { anchors.fill: parent; anchors.margins: 2; color: root.fillColor }
    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: root.accented ? 4 : 2
        color: root.accented ? root.accentColor : root.borderColor
    }
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 2
        anchors.rightMargin: 2
        anchors.topMargin: 2
        height: 1
        color: root.metallic ? Theme.PixelTheme.goldLight : "#99FFFFFF"
    }
    Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.margins: 2; width: 1; color: root.metallic ? Theme.PixelTheme.goldLight : root.borderColor }
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 2; height: 1; color: root.metallic ? Theme.PixelTheme.goldDark : root.borderColor }
    Rectangle { anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.margins: 2; width: 1; color: root.metallic ? Theme.PixelTheme.goldDark : root.borderColor }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.top: parent.top }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.top: parent.top }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.bottom: parent.bottom }
    Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.bottom: parent.bottom }

    Item {
        id: content
        anchors.fill: parent
        anchors.margins: root.padding + 1
    }
}
