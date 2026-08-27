import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property alias currentText: combo.currentText
    property alias currentIndex: combo.currentIndex
    property alias model: combo.model
    property string label: ""
    signal selected(string value)
    spacing: 3
    Label { text: root.label; color: "#665d50"; font.pixelSize: 11 }
    ComboBox {
        id: combo
        Layout.fillWidth: true
        activeFocusOnTab: true
        onActivated: root.selected(currentText)
    }
}
