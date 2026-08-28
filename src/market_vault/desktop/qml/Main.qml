import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components" as Components
import "pages" as Pages
import "theme" as Theme

ApplicationWindow {
    id: window
    objectName: "canaryWindow"
    visible: true
    width: 1100
    height: 700
    minimumWidth: 1000
    minimumHeight: 650
    title: i18nBridge.catalog["app.title"]
    color: Theme.PixelTheme.canvas
    font.family: Theme.PixelTheme.fontForLanguage(i18nBridge.language)

    FontLoader {
        id: fusionPixelFont
        objectName: "fusionPixelFont"
        source: Qt.resolvedUrl("../assets/fonts/fusion-pixel-12px-proportional-zh_hans-v2026.07.20/fusion-pixel-12px-proportional-zh_hans.otf")
    }

    function glyphForPage(pageId) {
        const glyphs = {
            "home": "home",
            "historical_data": "history",
            "trading_calendar": "calendar",
            "market_data": "chart",
            "inventory": "inventory",
            "coverage_audit": "audit",
            "intraday_audit": "pulse",
            "runs": "runs",
            "storage_cleanup": "storage"
        }
        return glyphs[pageId] || "info"
    }

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
            Layout.preferredHeight: Theme.PixelTheme.headerHeight
            color: Theme.PixelTheme.surfaceRaised

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 2
                color: Theme.PixelTheme.gold
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.topMargin: 8
                anchors.bottomMargin: 9
                spacing: 12

                RowLayout {
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 14
                    Components.GoldFloppyMark {
                        Layout.preferredWidth: 38
                        Layout.preferredHeight: 38
                    }
                    ColumnLayout {
                        spacing: 0
                        Label {
                            text: i18nBridge.catalog["app.title"]
                            color: Theme.PixelTheme.ink
                            font.family: Theme.PixelTheme.displayFont
                            font.pixelSize: Theme.PixelTheme.fontBrand
                            font.weight: Font.DemiBold
                        }
                        Label {
                            text: i18nBridge.catalog["app.subtitle"]
                            color: Theme.PixelTheme.inkMuted
                            font.family: Theme.PixelTheme.fontForLanguage(i18nBridge.language)
                            font.pixelSize: Theme.PixelTheme.fontSm
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                }

                Components.LanguageSwitcher {
                    objectName: "languageSwitcher"
                    i18n: i18nBridge
                    Layout.preferredWidth: 122
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Components.Sidebar {
                objectName: "sidebar"
                Layout.preferredWidth: Theme.PixelTheme.sidebarWidth
                Layout.fillHeight: true
                shell: shellController
                i18n: i18nBridge
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.PixelTheme.canvas

                ColumnLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    anchors.topMargin: 12
                    anchors.bottomMargin: 12
                    spacing: 9

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 31
                        spacing: 8
                        Components.PixelGlyph {
                            glyph: window.glyphForPage(shellController.currentPage)
                            color: Theme.PixelTheme.goldDark
                            Layout.preferredWidth: 24
                            Layout.preferredHeight: 24
                        }
                        Label {
                            id: pageTitle
                            objectName: "pageTitle"
                            text: i18nBridge.catalog[shellController.currentPageLabelKey]
                            color: Theme.PixelTheme.ink
                            font.family: Theme.PixelTheme.fontForLanguage(i18nBridge.language)
                            font.pixelSize: Theme.PixelTheme.fontTitle
                            font.weight: Font.DemiBold
                        }
                        Item {
                            objectName: "pageTitleDividerSlot"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 160
                            Layout.preferredWidth: 640
                            Layout.preferredHeight: 2
                            Layout.leftMargin: 16
                            Components.PixelDivider { objectName: "pageTitleDivider"; anchors.fill: parent }
                        }
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
            Layout.preferredHeight: Theme.PixelTheme.statusHeight
            color: Theme.PixelTheme.surfaceRaised
            Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; height: 1; color: Theme.PixelTheme.line }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                spacing: 8
                Components.PixelGlyph {
                    glyph: operationRuntime.error.length > 0 ? "warning" : "info"
                    color: operationRuntime.error.length > 0 ? Theme.PixelTheme.vermilion : Theme.PixelTheme.goldDark
                    Layout.preferredWidth: 14
                    Layout.preferredHeight: 14
                }
                Label {
                    text: {
                        i18nBridge.language
                        return i18nBridge.catalog["common.status"] + ": "
                            + i18nBridge.statusLabel(operationRuntime.status)
                            + (operationRuntime.activeOperation.length > 0
                                ? " / " + i18nBridge.operationLabel(operationRuntime.activeOperation) : "")
                    }
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Components.PixelProgress {
                    running: operationRuntime.busy
                    Layout.preferredWidth: operationRuntime.busy ? 54 : 0
                    Layout.preferredHeight: 10
                }
                Item { Layout.fillWidth: true }
                Label {
                    text: i18nBridge.catalog["common.error"] + ": " + operationRuntime.error
                    visible: operationRuntime.error.length > 0
                    color: Theme.PixelTheme.vermilionDark
                    horizontalAlignment: Text.AlignRight
                    elide: Text.ElideRight
                    Layout.maximumWidth: 560
                }
            }
        }
    }

    Dialog {
        id: closeBusyDialog
        title: i18nBridge.catalog["common.running"]
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        closePolicy: Popup.CloseOnEscape
        standardButtons: Dialog.NoButton
        padding: Theme.PixelTheme.panelPadding
        background: Rectangle {
            color: Theme.PixelTheme.surfaceRaised
            border.color: Theme.PixelTheme.warning
            border.width: 2
        }
        contentItem: ColumnLayout {
            spacing: Theme.PixelTheme.spacingMd
            Label {
                Layout.preferredWidth: 340
                text: i18nBridge.catalog["common.close_busy"]
                color: Theme.PixelTheme.ink
                wrapMode: Text.Wrap
            }
            Components.PixelButton {
                Layout.alignment: Qt.AlignRight
                text: i18nBridge.catalog["common.confirm"]
                onClicked: closeBusyDialog.close()
            }
        }
    }
}
