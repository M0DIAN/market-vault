import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

CheckBox {
    id: control
    activeFocusOnTab: true
    implicitHeight: Theme.PixelTheme.controlHeight
    spacing: 7
    indicator: Item {
        implicitWidth: 18
        implicitHeight: 18
        x: 0
        y: Math.round((control.height - height) / 2)
        Rectangle { anchors.fill: parent; color: control.activeFocus ? Theme.PixelTheme.goldDark : Theme.PixelTheme.line }
        Rectangle { anchors.fill: parent; anchors.margins: control.activeFocus ? 3 : 1; color: Theme.PixelTheme.surfaceRaised }
        Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 3; height: 1; color: Theme.PixelTheme.goldLight }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.top: parent.top }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.bottom: parent.bottom }
        PixelGlyph { anchors.fill: parent; anchors.margins: 2; glyph: "check"; color: Theme.PixelTheme.goldDark; visible: control.checked }
    }
    contentItem: Text {
        text: control.text
        font.family: Theme.PixelTheme.uiFont
        font.pixelSize: Theme.PixelTheme.fontMd
        color: Theme.PixelTheme.ink
        verticalAlignment: Text.AlignVCenter
        leftPadding: control.indicator.width + control.spacing
        elide: Text.ElideRight
    }
    opacity: enabled ? 1 : Theme.PixelTheme.disabledOpacity
}
