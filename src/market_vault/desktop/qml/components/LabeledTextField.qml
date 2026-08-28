import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    implicitWidth: Theme.PixelTheme.formFieldWidth
    Layout.fillWidth: true
    Layout.minimumWidth: Theme.PixelTheme.formFieldMinimumWidth
    Layout.maximumWidth: Theme.PixelTheme.formFieldWidth
    property alias text: field.text
    property string label: ""
    property string placeholderText: ""
    signal edited(string value)
    spacing: 4
    Label {
        text: root.label
        color: Theme.PixelTheme.inkMuted
        font.family: Theme.PixelTheme.uiFont
        font.pixelSize: Theme.PixelTheme.fontSm
        elide: Text.ElideRight
        Layout.fillWidth: true
    }
    PixelTextField {
        id: field
        Layout.fillWidth: true
        placeholderText: root.placeholderText
        onTextEdited: root.edited(text)
    }
}
