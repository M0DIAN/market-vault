import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    property string text: ""
    property string glyph: "inventory"
    spacing: Theme.PixelTheme.spacingSm
    PixelGlyph {
        Layout.alignment: Qt.AlignHCenter
        Layout.preferredWidth: 24
        Layout.preferredHeight: 24
        glyph: root.glyph
        color: Theme.PixelTheme.gold
    }
    Label {
        Layout.alignment: Qt.AlignHCenter
        text: root.text
        color: Theme.PixelTheme.inkMuted
        font.family: Theme.PixelTheme.uiFont
        font.pixelSize: Theme.PixelTheme.fontMd
    }
}
