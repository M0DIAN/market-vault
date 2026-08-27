import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    objectName: "canaryWindow"
    visible: true
    width: 840
    height: 620
    minimumWidth: 720
    minimumHeight: 560
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

                Button {
                    id: dashboardButton
                    objectName: "dashboardButton"
                    Layout.alignment: Qt.AlignHCenter
                    text: dashboardController.backendConfigured
                        ? (dashboardController.busy ? "REFRESHING..." : "REFRESH DASHBOARD")
                        : "DASHBOARD UNCONFIGURED"
                    enabled: dashboardController.backendConfigured && !dashboardController.busy
                    onClicked: dashboardController.refresh()
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

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Dashboard: " + dashboardController.status
                    color: "#665d50"
                    font.pixelSize: 14
                }

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    visible: dashboardController.error.length > 0
                    text: dashboardController.error
                    color: "#8b2f24"
                    font.pixelSize: 13
                }

                GridLayout {
                    Layout.alignment: Qt.AlignHCenter
                    columns: 3
                    columnSpacing: 24
                    rowSpacing: 8

                    Repeater {
                        model: [
                            "Symbols",
                            "Snapshots",
                            "Latest rows",
                            "Completed dates",
                            "Incomplete dates",
                            "Latest trade date"
                        ]

                        ColumnLayout {
                            Layout.minimumWidth: 130

                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: modelData
                                color: "#665d50"
                                font.pixelSize: 12
                            }

                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: dashboardController.metrics[modelData] || "-"
                                color: "#2b2418"
                                font.pixelSize: 16
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }
            }
        }
    }
}
