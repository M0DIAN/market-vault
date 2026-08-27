import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components" as Components
import "pages" as Pages

ApplicationWindow {
    id: window
    objectName: "canaryWindow"
    visible: true
    width: 1100
    height: 700
    minimumWidth: 1000
    minimumHeight: 650
    title: i18nBridge.catalog["app.title"]
    color: "#f3eee2"
    onClosing: function(close) {
        if (!operationRuntime.requestShutdown()) {
            close.accepted = false
            closeBusyDialog.open()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 76
            color: "#fffaf0"
            border.color: "#d8c9a6"
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 22
                anchors.rightMargin: 22
                spacing: 16

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1

                    Label {
                        text: i18nBridge.catalog["app.title"]
                        color: "#2b2418"
                        font.pixelSize: 24
                        font.weight: Font.DemiBold
                    }

                    Label {
                        text: i18nBridge.catalog["app.subtitle"]
                        color: "#665d50"
                        font.pixelSize: 13
                    }
                }

                Label {
                    text: i18nBridge.catalog["language.control"]
                    color: "#665d50"
                    font.pixelSize: 12
                }

                Components.LanguageSwitcher {
                    objectName: "languageSwitcher"
                    i18n: i18nBridge
                    Layout.preferredWidth: 120
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Components.Sidebar {
                objectName: "sidebar"
                Layout.preferredWidth: 220
                Layout.fillHeight: true
                shell: shellController
                i18n: i18nBridge
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: "#f3eee2"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: 12

                    Label {
                        id: pageTitle
                        objectName: "pageTitle"
                        text: i18nBridge.catalog[shellController.currentPageLabelKey]
                        color: "#2b2418"
                        font.pixelSize: 22
                        font.weight: Font.DemiBold
                    }

                    StackLayout {
                        id: pageContent
                        objectName: "pageContent"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        currentIndex: shellController.currentPageIndex

                        Pages.HomePage { objectName: "homePage"; dashboard: dashboardController; desktop: desktopBridge; i18n: i18nBridge }
                        Pages.HistoricalDataPage { objectName: "historicalDataPage"; controller: historicalDataController; i18n: i18nBridge }
                        Pages.TradingCalendarPage { objectName: "tradingCalendarPage"; controller: tradingCalendarController; i18n: i18nBridge }
                        Pages.MarketDataPage { objectName: "marketDataPage"; controller: marketDataController; i18n: i18nBridge }
                        Pages.InventoryPage { objectName: "inventoryPage"; controller: inventoryController; i18n: i18nBridge }
                        Pages.AuditPage { objectName: "coverageAuditPage"; tableObjectName: "coverageAuditTable"; controller: coverageAuditController; i18n: i18nBridge }
                        Pages.AuditPage { objectName: "intradayAuditPage"; tableObjectName: "intradayAuditTable"; controller: intradayAuditController; i18n: i18nBridge }
                        Pages.RunsPage { objectName: "runsPage"; controller: runsController; i18n: i18nBridge }
                        Pages.StorageCleanupPage { objectName: "storageCleanupPage"; controller: storageCleanupController; i18n: i18nBridge }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 34
            color: "#fffaf0"
            border.color: "#d8c9a6"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                Label {
                    text: {
                        i18nBridge.language
                        return i18nBridge.catalog["common.status"] + ": "
                            + i18nBridge.statusLabel(operationRuntime.status)
                            + (operationRuntime.activeOperation.length > 0
                                ? " / " + i18nBridge.operationLabel(
                                    operationRuntime.activeOperation) : "")
                    }
                    color: "#665d50"
                }
                Item { Layout.fillWidth: true }
                Label {
                    Layout.fillWidth: true
                    text: i18nBridge.catalog["common.error"] + ": "
                        + operationRuntime.error
                    visible: operationRuntime.error.length > 0
                    color: "#8b2f24"
                    horizontalAlignment: Text.AlignRight
                    wrapMode: Text.Wrap
                    Layout.maximumWidth: 600
                }
            }
        }
    }

    Dialog {
        id: closeBusyDialog
        title: i18nBridge.catalog["common.running"]
        modal: true
        closePolicy: Popup.CloseOnEscape
        standardButtons: Dialog.Ok
        Label { text: i18nBridge.catalog["common.close_busy"]; wrapMode: Text.Wrap }
    }
}
