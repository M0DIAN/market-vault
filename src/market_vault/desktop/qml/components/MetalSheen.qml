import QtQuick
import "../theme" as Theme

Item {
    id: root
    property bool active: false
    property color sheenColor: "#66FFF4D4"
    property int duration: Theme.PixelTheme.motionSlow
    clip: true

    Rectangle {
        id: strip
        width: Math.max(8, root.width * 0.16)
        height: root.height
        x: -width
        color: root.sheenColor
        opacity: 0.58
    }

    NumberAnimation {
        id: sweep
        target: strip
        property: "x"
        from: -strip.width
        to: root.width
        duration: root.duration
        easing.type: Easing.InOutQuad
    }

    onActiveChanged: {
        if (active) {
            strip.x = -strip.width
            sweep.restart()
        } else {
            sweep.stop()
            strip.x = -strip.width
        }
    }
}
