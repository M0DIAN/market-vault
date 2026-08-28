import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Item {
    id: root
    required property var tableModel
    required property var i18n
    property bool paged: false
    signal previousRequested()
    signal nextRequested()

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingSm

        PixelFrame {
            Layout.fillWidth: true
            Layout.fillHeight: true
            padding: 1
            fillColor: Theme.PixelTheme.surfaceRaised
            borderColor: Theme.PixelTheme.line

            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                visible: root.tableModel.totalRows > 0

                HorizontalHeaderView {
                    id: header
                    objectName: root.objectName + "Header"
                    Layout.fillWidth: true
                    syncView: table
                    clip: true
                    delegate: Rectangle {
                        implicitWidth: 145
                        implicitHeight: Theme.PixelTheme.tableHeaderHeight
                        color: Theme.PixelTheme.goldPale
                        border.color: Theme.PixelTheme.goldDark
                        required property string display
                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: 1
                            color: Theme.PixelTheme.goldHighlight
                        }
                        Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.PixelTheme.goldDark }
                        Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 1; color: Theme.PixelTheme.goldLight }
                        Label {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            text: {
                                root.i18n.language
                                return root.i18n.columnLabel(parent.display)
                            }
                            color: Theme.PixelTheme.ink
                            font.family: Theme.PixelTheme.fontForLanguage(root.i18n.language)
                            font.pixelSize: Theme.PixelTheme.fontSm
                            font.weight: Font.DemiBold
                        }
                    }
                }

                TableView {
                    id: table
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: root.tableModel
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.horizontal: PixelScrollBar {}
                    ScrollBar.vertical: PixelScrollBar {}
                    delegate: Rectangle {
                        implicitWidth: 145
                        implicitHeight: Theme.PixelTheme.tableRowHeight
                        color: row % 2 === 0 ? Theme.PixelTheme.surfaceRaised : Theme.PixelTheme.surface
                        border.color: Theme.PixelTheme.lineSoft
                        required property string display
                        required property int row
                        Label {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            text: parent.display
                            color: Theme.PixelTheme.ink
                            font.family: Theme.PixelTheme.dataFont
                            font.pixelSize: Theme.PixelTheme.fontSm
                        }
                    }
                }
            }

            PixelEmptyState {
                objectName: root.objectName + "EmptyState"
                anchors.centerIn: parent
                visible: root.tableModel.totalRows === 0
                text: root.i18n.catalog["common.no_data"]
            }
        }

        PixelPagination {
            Layout.fillWidth: true
            visible: root.paged
            tableModel: root.tableModel
            i18n: root.i18n
            onPreviousRequested: root.previousRequested()
            onNextRequested: root.nextRequested()
        }
    }
}
