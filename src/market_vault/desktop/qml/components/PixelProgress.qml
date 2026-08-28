import QtQuick
import "../theme" as Theme

Item {
    id: root
    property bool running: false
    implicitWidth: running ? 54 : 0
    implicitHeight: 10
    visible: running

    Rectangle { anchors.fill: parent; color: Theme.PixelTheme.surfaceMuted; border.color: Theme.PixelTheme.goldDark; border.width: 1 }
    Row {
        anchors.centerIn: parent
        spacing: 2
        Repeater {
            model: 4
            Rectangle {
                required property int index
                width: 9
                height: 4
                color: Theme.PixelTheme.gold
                opacity: root.running && index === pulse.frame ? 1 : (root.running ? 0.2 : 0)
            }
        }
    }
    Timer {
        id: pulse
        property int frame: 0
        interval: 140
        repeat: true
        running: root.running && root.visible
        onTriggered: frame = (frame + 1) % 4
        onRunningChanged: if (!running) frame = 0
    }
}
