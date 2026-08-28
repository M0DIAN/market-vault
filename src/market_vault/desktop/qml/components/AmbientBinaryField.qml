import QtQuick
import "../theme" as Theme

Item {
    id: root
    clip: true
    property int phase: 0
    readonly property var rows: [
        "01001101 01000001 01010010 01001011 01000101 01010100",
        "00110001 01101101 00100000 01000001 01001100 01001100",
        "01010011 01001110 01000001 01010000 01010011 01001000",
        "01010010 01010101 01001110 00100000 00110000 00110001",
        "01000011 01000001 01010100 01000001 01001100 01001111",
        "01010110 01000001 01010101 01001100 01010100 00100000"
    ]

    Repeater {
        model: root.rows
        Text {
            required property string modelData
            required property int index
            x: root.width * 0.26 + ((index * 37 + root.phase * 5) % 68)
            y: 5 + index * 15
            text: modelData
            color: index % 3 === 0 ? Theme.PixelTheme.goldDark : Theme.PixelTheme.inkMuted
            opacity: index % 3 === 0 ? 0.060 : 0.040
            font.family: Theme.PixelTheme.displayFont
            font.pixelSize: 9
            font.letterSpacing: 0
        }
    }

    Timer {
        interval: 1600
        repeat: true
        running: root.visible
        onTriggered: root.phase = (root.phase + 1) % 97
    }
}
