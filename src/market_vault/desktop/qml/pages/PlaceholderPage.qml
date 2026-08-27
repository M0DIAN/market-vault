import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    required property string pageLabel
    required property string message

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 520)
        spacing: 12

        Label {
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: true
            text: pageLabel
            horizontalAlignment: Text.AlignHCenter
            color: "#2b2418"
            font.pixelSize: 20
            font.weight: Font.DemiBold
            wrapMode: Text.Wrap
        }

        Label {
            objectName: "placeholderMessage"
            Layout.fillWidth: true
            text: message
            horizontalAlignment: Text.AlignHCenter
            color: "#665d50"
            font.pixelSize: 14
            wrapMode: Text.Wrap
        }
    }
}
