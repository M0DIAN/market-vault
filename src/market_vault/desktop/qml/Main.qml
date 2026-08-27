import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    objectName: "canaryWindow"
    visible: true
    width: 720
    height: 420
    minimumWidth: 560
    minimumHeight: 340
    title: "MarketVault QML Canary"
    color: "#f3eee2"

    Rectangle {
        anchors.fill: parent
        color: "#f3eee2"

        Rectangle {
            anchors.fill: parent
            anchors.margins: 24
            color: "#fffaf0"
            border.color: "#c59a3d"
            border.width: 1

            ColumnLayout {
                anchors.centerIn: parent
                spacing: 18

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "MarketVault"
                    color: "#2b2418"
                    font.pixelSize: 30
                    font.weight: Font.DemiBold
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "PySide6 + QML migration canary"
                    color: "#665d50"
                    font.pixelSize: 16
                }

                Button {
                    id: pingButton
                    objectName: "pingButton"
                    Layout.alignment: Qt.AlignHCenter
                    text: "PING PYTHON"
                    onClicked: desktopBridge.ping()
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Status:"
                    color: "#665d50"
                    font.pixelSize: 14
                }

                Label {
                    id: statusValue
                    objectName: "statusValue"
                    Layout.alignment: Qt.AlignHCenter
                    text: desktopBridge.status
                    color: "#8a651a"
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }
            }
        }
    }
}
