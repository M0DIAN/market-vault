import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    objectName: "canaryWindow"
    visible: true
    width: 900
    height: 700
    minimumWidth: 760
    minimumHeight: 620
    title: "MarketVault QML Canary"
    color: "#f3eee2"

    Rectangle {
        anchors.fill: parent
        anchors.margins: 24
        color: "#fffaf0"
        border.color: "#c59a3d"
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12

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

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 12

                Button {
                    id: pingButton
                    objectName: "pingButton"
                    text: "PING PYTHON"
                    onClicked: desktopBridge.ping()
                }

                Button {
                    id: dashboardButton
                    objectName: "dashboardButton"
                    text: dashboardController.backendConfigured
                        ? (dashboardController.busy ? "REFRESHING..." : "REFRESH DASHBOARD")
                        : "DASHBOARD UNCONFIGURED"
                    enabled: dashboardController.backendConfigured && !dashboardController.busy
                    onClicked: dashboardController.refresh()
                }
            }

            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 8

                Label {
                    text: "Status:"
                    color: "#665d50"
                    font.pixelSize: 14
                }

                Label {
                    id: statusValue
                    objectName: "statusValue"
                    text: desktopBridge.status
                    color: "#8a651a"
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }

                Label {
                    text: "Dashboard: " + dashboardController.status
                    color: "#665d50"
                    font.pixelSize: 14
                }
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

            Label {
                text: "Recent Runs"
                color: "#2b2418"
                font.pixelSize: 17
                font.weight: Font.DemiBold
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 180

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    visible: dashboardController.recentRunsModel.totalRows > 0

                    HorizontalHeaderView {
                        id: recentRunsHeader
                        objectName: "recentRunsHeader"
                        Layout.fillWidth: true
                        syncView: recentRunsTable
                        clip: true

                        delegate: Rectangle {
                            implicitWidth: 150
                            implicitHeight: 30
                            color: "#eee4cf"
                            border.color: "#c9b990"
                            border.width: 1

                            required property string display

                            Label {
                                anchors.fill: parent
                                anchors.leftMargin: 7
                                anchors.rightMargin: 7
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                text: parent.display
                                color: "#2b2418"
                                font.weight: Font.DemiBold
                            }
                        }
                    }

                    TableView {
                        id: recentRunsTable
                        objectName: "recentRunsTable"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        model: dashboardController.recentRunsModel
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.horizontal: ScrollBar {}
                        ScrollBar.vertical: ScrollBar {}

                        delegate: Rectangle {
                            implicitWidth: 150
                            implicitHeight: 30
                            color: row % 2 === 0 ? "#fffaf0" : "#f8f1e4"
                            border.color: "#e1d6bd"
                            border.width: 1

                            required property string display
                            required property int row

                            Label {
                                anchors.fill: parent
                                anchors.leftMargin: 7
                                anchors.rightMargin: 7
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                text: parent.display
                                color: "#2b2418"
                            }
                        }
                    }
                }

                Label {
                    id: recentRunsEmptyState
                    objectName: "recentRunsEmptyState"
                    anchors.centerIn: parent
                    visible: dashboardController.recentRunsModel.totalRows === 0
                    text: "No recent runs"
                    color: "#665d50"
                    font.pixelSize: 14
                }
            }
        }
    }
}
