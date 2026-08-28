import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Button {
    id: control
    property string variant: "secondary"
    property string glyph: ""
    property bool compact: false
    implicitHeight: compact ? Theme.PixelTheme.compactControlHeight : Theme.PixelTheme.controlHeight
    implicitWidth: Math.max(72, contentRow.implicitWidth + 24)
    leftPadding: 12
    rightPadding: 12
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.5

    readonly property color frameColor: variant === "danger"
        ? Theme.PixelTheme.vermilionDark
        : (variant === "primary" ? Theme.PixelTheme.goldDark : Theme.PixelTheme.line)
    readonly property color baseColor: variant === "danger"
        ? Theme.PixelTheme.vermilion
        : (variant === "primary" ? Theme.PixelTheme.goldPale
           : (variant === "ghost" ? Theme.PixelTheme.transparent : Theme.PixelTheme.surfaceRaised))
    readonly property color textColor: variant === "danger"
        ? Theme.PixelTheme.surfaceRaised
        : (variant === "primary" ? Theme.PixelTheme.goldDark : Theme.PixelTheme.ink)

    contentItem: RowLayout {
        id: contentRow
        spacing: 6
        PixelGlyph {
            visible: control.glyph.length > 0
            glyph: control.glyph
            color: control.textColor
            Layout.preferredWidth: 15
            Layout.preferredHeight: 15
        }
        Label {
            text: control.text
            color: control.textColor
            font.family: Theme.PixelTheme.uiFont
            font.pixelSize: Theme.PixelTheme.fontMd
            font.weight: control.variant === "primary" ? Font.DemiBold : Font.Normal
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
    }

    background: Item {
        Rectangle { anchors.fill: parent; color: control.activeFocus ? Theme.PixelTheme.goldDark : control.frameColor }
        Rectangle {
            anchors.fill: parent
            anchors.margins: control.activeFocus ? 3 : 1
            color: control.down
                ? Qt.darker(control.baseColor, 1.08)
                : (control.hovered ? Qt.lighter(control.baseColor, 1.04) : control.baseColor)
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: control.activeFocus ? 4 : 2
            anchors.rightMargin: control.activeFocus ? 4 : 2
            anchors.topMargin: control.activeFocus ? 4 : 2
            height: 1
            color: control.variant === "danger" ? "#88F7D8C7" : Theme.PixelTheme.goldHighlight
            opacity: control.variant === "ghost" ? 0 : 0.8
        }
        Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.margins: control.activeFocus ? 4 : 2; width: 1; color: control.variant === "danger" ? Theme.PixelTheme.vermilionDark : Theme.PixelTheme.goldLight }
        Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: control.activeFocus ? 4 : 2; height: 1; color: control.variant === "danger" ? Theme.PixelTheme.vermilionDark : Theme.PixelTheme.goldDark }
        Rectangle { anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.margins: control.activeFocus ? 4 : 2; width: 1; color: control.variant === "danger" ? Theme.PixelTheme.vermilionDark : Theme.PixelTheme.goldDark }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.top: parent.top }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.top: parent.top }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.bottom: parent.bottom }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.bottom: parent.bottom }
    }

    transform: Translate { x: control.down ? 1 : 0; y: control.down ? 1 : 0 }
    Behavior on opacity { NumberAnimation { duration: Theme.PixelTheme.motionFast } }
}
