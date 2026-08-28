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
    property alias currentText: combo.currentText
    property alias currentIndex: combo.currentIndex
    property alias model: combo.model
    property string label: ""
    signal selected(string value)
    spacing: 4
    Label {
        text: root.label
        color: Theme.PixelTheme.inkMuted
        font.family: Theme.PixelTheme.uiFont
        font.pixelSize: Theme.PixelTheme.fontSm
        elide: Text.ElideRight
        Layout.fillWidth: true
    }
    PixelComboBox {
        id: combo
        Layout.fillWidth: true
        onActivated: root.selected(currentText)
    }
}
