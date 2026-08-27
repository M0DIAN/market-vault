import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property alias text: field.text
    property string label: ""
    property string placeholderText: ""
    signal edited(string value)
    spacing: 3
    Label { text: root.label; color: "#665d50"; font.pixelSize: 11 }
    TextField {
        id: field
        Layout.fillWidth: true
        placeholderText: root.placeholderText
        selectByMouse: true
        onTextEdited: root.edited(text)
    }
}
