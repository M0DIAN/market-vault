import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Rectangle {
    id: sidebar
    required property var shell
    required property var i18n
    color: Theme.PixelTheme.surface
    border.color: Theme.PixelTheme.line
    border.width: 1

    function glyphFor(pageId) {
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

    Rectangle {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 2
        color: Theme.PixelTheme.canvasAlt
    }

    ScrollView {
        anchors.fill: parent
        anchors.rightMargin: 2
        contentWidth: availableWidth
        clip: true
        ScrollBar.vertical: PixelScrollBar {}

        Column {
            width: parent.width
            topPadding: 10
            bottomPadding: 12
            spacing: 2

            Repeater {
                model: sidebar.shell.pages

                Column {
                    required property var modelData
                    width: parent.width
                    spacing: 2

                    Label {
                        visible: modelData.showGroup
                        height: visible ? implicitHeight + 12 : 0
                        leftPadding: 18
                        topPadding: 10
                        text: sidebar.i18n.catalog[modelData.groupKey]
                        color: Theme.PixelTheme.goldDark
                        font.family: Theme.PixelTheme.displayFont
                        font.pixelSize: Theme.PixelTheme.fontXs
                        font.weight: Font.DemiBold
                    }

                    Button {
                        id: navigationButton
                        objectName: "nav_" + modelData.id
                        width: parent.width - 12
                        height: 38
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: sidebar.i18n.catalog[modelData.labelKey]
                        checkable: true
                        activeFocusOnTab: true
                        checked: sidebar.shell.currentPage === modelData.id
                        onClicked: sidebar.shell.selectPage(modelData.id)

                        contentItem: RowLayout {
                            spacing: 9
                            PixelGlyph {
                                glyph: sidebar.glyphFor(modelData.id)
                                color: navigationButton.checked ? Theme.PixelTheme.goldDark : Theme.PixelTheme.inkMuted
                                Layout.preferredWidth: 24
                                Layout.preferredHeight: 24
                            }
                            Label {
                                text: navigationButton.text
                                color: navigationButton.checked ? Theme.PixelTheme.ink : Theme.PixelTheme.inkMuted
                                font.family: Theme.PixelTheme.fontForLanguage(sidebar.i18n.language)
                                font.pixelSize: Theme.PixelTheme.fontMd
                                font.weight: navigationButton.checked ? Font.DemiBold : Font.Normal
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }

                        background: Item {
                            Rectangle {
                                anchors.fill: parent
                                color: navigationButton.activeFocus ? Theme.PixelTheme.goldDark
                                    : (navigationButton.checked ? Theme.PixelTheme.gold : Theme.PixelTheme.transparent)
                            }
                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: navigationButton.activeFocus ? 2 : (navigationButton.checked ? 1 : 0)
                                color: navigationButton.checked ? Theme.PixelTheme.goldPale
                                    : (navigationButton.hovered ? Theme.PixelTheme.surfaceMuted : Theme.PixelTheme.transparent)
                            }
                            Rectangle {
                                anchors.left: parent.left
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                width: navigationButton.checked ? 3 : 0
                                color: Theme.PixelTheme.goldDark
                            }
                            MetalSheen {
                                anchors.fill: parent
                                active: navigationButton.hovered && navigationButton.checked
                                visible: navigationButton.checked
                            }
                        }
                    }
                }
            }
        }
    }
}
