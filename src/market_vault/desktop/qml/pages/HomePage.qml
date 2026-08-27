import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components

Item {
    id: home
    required property var dashboard
    required property var desktop
    required property var i18n

    readonly property var metricDefinitions: [
        {"sourceKey": "Symbols", "labelKey": "metric.symbols"},
        {"sourceKey": "Snapshots", "labelKey": "metric.snapshots"},
        {"sourceKey": "Latest rows", "labelKey": "metric.latest_rows"},
        {"sourceKey": "Completed dates", "labelKey": "metric.completed_dates"},
        {"sourceKey": "Incomplete dates", "labelKey": "metric.incomplete_dates"},
        {"sourceKey": "Latest trade date", "labelKey": "metric.latest_trade_date"}
    ]

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Button {
                id: pingButton
                objectName: "pingButton"
                text: home.i18n.catalog["home.ping"]
                onClicked: home.desktop.ping()
            }

            Button {
                id: dashboardButton
                objectName: "dashboardButton"
                text: home.dashboard.backendConfigured
                    ? (home.dashboard.busy
                        ? home.i18n.catalog["home.refreshing"]
                        : home.i18n.catalog["home.refresh"])
                    : home.i18n.catalog["home.unconfigured"]
                enabled: home.dashboard.backendConfigured && !home.dashboard.busy
                onClicked: home.dashboard.refresh()
            }

            Item { Layout.fillWidth: true }

            Label {
                text: home.i18n.catalog["status.bridge"] + ":"
                color: "#665d50"
                font.pixelSize: 12
            }

            Label {
                id: statusValue
                objectName: "statusValue"
                text: home.desktop.status
                color: "#8a651a"
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }

            Label {
                text: {
                    home.i18n.language
                    return home.i18n.catalog["status.dashboard"]
                        + ": " + home.i18n.statusLabel(home.dashboard.status)
                }
                color: "#665d50"
                font.pixelSize: 12
            }
        }

        Label {
            Layout.fillWidth: true
            visible: home.dashboard.error.length > 0
            text: home.i18n.catalog["common.error"] + ": "
                + home.dashboard.error
            color: "#8b2f24"
            font.pixelSize: 13
            wrapMode: Text.Wrap
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 3
            columnSpacing: 12
            rowSpacing: 10

            Repeater {
                model: home.metricDefinitions

                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 68
                    color: "#fffaf0"
                    border.color: "#d8c9a6"
                    border.width: 1

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 2

                        Label {
                            text: home.i18n.catalog[modelData.labelKey]
                            color: "#665d50"
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }

                        Label {
                            text: home.dashboard.metrics[modelData.sourceKey] || "-"
                            color: "#2b2418"
                            font.pixelSize: 17
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        Label {
            text: home.i18n.catalog["home.recent_runs"]
            color: "#2b2418"
            font.pixelSize: 17
            font.weight: Font.DemiBold
        }

        Components.DataTable {
            objectName: "recentRunsTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 180
            tableModel: home.dashboard.recentRunsModel
            i18n: home.i18n
            paged: false
        }
    }
}
