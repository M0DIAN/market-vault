import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: home
    required property var dashboard
    required property var desktop
    required property var i18n

    readonly property var metricDefinitions: [
        {"objectKey": "symbols", "sourceKey": "Symbols", "labelKey": "metric.symbols", "glyph": "chart"},
        {"objectKey": "snapshots", "sourceKey": "Snapshots", "labelKey": "metric.snapshots", "glyph": "storage"},
        {"objectKey": "latestRows", "sourceKey": "Latest rows", "labelKey": "metric.latest_rows", "glyph": "inventory"},
        {"objectKey": "completedDates", "sourceKey": "Completed dates", "labelKey": "metric.completed_dates", "glyph": "check"},
        {"objectKey": "incompleteDates", "sourceKey": "Incomplete dates", "labelKey": "metric.incomplete_dates", "glyph": "warning"},
        {"objectKey": "latestTradeDate", "sourceKey": "Latest trade date", "labelKey": "metric.latest_trade_date", "glyph": "calendar"}
    ]

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingSm

        Components.PixelPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: 84
            padding: 0
            accented: true
            fillColor: Theme.PixelTheme.surfaceRaised

            Components.AmbientBinaryField { anchors.fill: parent }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                spacing: 10

                Item {
                    id: applicationIconContainer
                    objectName: "homeApplicationIconContainer"
                    readonly property bool applicationIconReady:
                        applicationIcon.status === Image.Ready
                    Layout.preferredWidth: 42
                    Layout.preferredHeight: 42
                    Layout.alignment: Qt.AlignVCenter

                    Image {
                        id: applicationIcon
                        objectName: "homeApplicationIcon"
                        anchors.fill: parent
                        source: home.desktop.applicationIconUrl
                        fillMode: Image.PreserveAspectFit
                        smooth: false
                        mipmap: false
                        visible: applicationIconContainer.applicationIconReady
                    }

                    Components.GoldFloppyMark {
                        objectName: "homeApplicationIconFallback"
                        anchors.centerIn: parent
                        width: 34
                        height: 34
                        visible: !applicationIconContainer.applicationIconReady
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    Label {
                        text: home.i18n.catalog["page.home"]
                        color: Theme.PixelTheme.ink
                        font.family: Theme.PixelTheme.displayFont
                        font.pixelSize: Theme.PixelTheme.fontLg
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: home.i18n.catalog["app.subtitle"]
                        color: Theme.PixelTheme.inkMuted
                        font.pixelSize: Theme.PixelTheme.fontSm
                    }
                }

                Components.PixelButton {
                    id: pingButton
                    objectName: "pingButton"
                    variant: "ghost"
                    glyph: "network"
                    text: home.i18n.catalog["home.ping"]
                    onClicked: home.desktop.ping()
                }

                Components.PixelButton {
                    id: dashboardButton
                    objectName: "dashboardButton"
                    variant: "primary"
                    glyph: "refresh"
                    text: home.dashboard.backendConfigured
                        ? (home.dashboard.busy ? home.i18n.catalog["home.refreshing"] : home.i18n.catalog["home.refresh"])
                        : home.i18n.catalog["home.unconfigured"]
                    enabled: home.dashboard.backendConfigured && !home.dashboard.busy
                    onClicked: home.dashboard.refresh()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Components.PixelStatusBadge {
                status: home.dashboard.status
                text: {
                    home.i18n.language
                    return home.i18n.catalog["status.dashboard"] + ": "
                        + home.i18n.statusLabel(home.dashboard.status)
                }
            }
            Components.PixelTag {
                text: home.i18n.catalog["status.bridge"] + ":"
                accentColor: Theme.PixelTheme.line
            }
            Label {
                id: statusValue
                objectName: "statusValue"
                text: home.desktop.status
                color: Theme.PixelTheme.goldDark
                font.pixelSize: Theme.PixelTheme.fontSm
                font.weight: Font.DemiBold
            }
            Item { Layout.fillWidth: true }
            Label {
                visible: home.dashboard.error.length > 0
                text: home.i18n.catalog["common.error"] + ": " + home.dashboard.error
                color: Theme.PixelTheme.vermilionDark
                font.pixelSize: Theme.PixelTheme.fontSm
                elide: Text.ElideRight
                Layout.maximumWidth: 500
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 3
            columnSpacing: Theme.PixelTheme.spacingSm
            rowSpacing: Theme.PixelTheme.spacingSm

            Repeater {
                model: home.metricDefinitions

                Components.PixelPanel {
                    required property var modelData
                    objectName: "homeMetricCard_" + modelData.objectKey
                    Layout.fillWidth: true
                    Layout.preferredHeight: 72
                    padding: 9
                    fillColor: Theme.PixelTheme.surfaceRaised
                    accentColor: modelData.sourceKey === "Incomplete dates"
                        ? Theme.PixelTheme.warning : Theme.PixelTheme.gold
                    accented: true

                    RowLayout {
                        anchors.fill: parent
                        spacing: 9
                        Components.PixelGlyph {
                            objectName: "homeMetricGlyph_" + modelData.objectKey
                            glyph: modelData.glyph
                            color: Theme.PixelTheme.goldDark
                            Layout.preferredWidth: 24
                            Layout.preferredHeight: 24
                            Layout.alignment: Qt.AlignVCenter
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Label {
                                text: home.i18n.catalog[modelData.labelKey]
                                color: Theme.PixelTheme.inkMuted
                                font.pixelSize: Theme.PixelTheme.fontSm
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Label {
                                text: home.dashboard.metrics[modelData.sourceKey] || "-"
                                color: Theme.PixelTheme.ink
                                font.family: Theme.PixelTheme.displayFont
                                font.pixelSize: Theme.PixelTheme.fontLg
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 7
            Components.PixelGlyph {
                glyph: "runs"
                color: Theme.PixelTheme.goldDark
                Layout.preferredWidth: 16
                Layout.preferredHeight: 16
            }
            Label {
                text: home.i18n.catalog["home.recent_runs"]
                color: Theme.PixelTheme.ink
                font.family: Theme.PixelTheme.fontForLanguage(home.i18n.language)
                font.pixelSize: Theme.PixelTheme.fontLg
                font.weight: Font.DemiBold
            }
            Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.PixelTheme.lineSoft }
        }

        Components.DataTable {
            objectName: "recentRunsTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 150
            tableModel: home.dashboard.recentRunsModel
            i18n: home.i18n
            paged: false
        }
    }
}
