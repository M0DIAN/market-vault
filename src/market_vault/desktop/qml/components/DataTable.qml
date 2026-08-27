import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    required property var tableModel
    required property var i18n
    property bool paged: false
    signal previousRequested()
    signal nextRequested()

    ColumnLayout {
        anchors.fill: parent
        spacing: 6

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

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
                        implicitHeight: 30
                        color: "#eee4cf"
                        border.color: "#c9b990"
                        required property string display
                        Label {
                            anchors.fill: parent
                            anchors.leftMargin: 7
                            anchors.rightMargin: 7
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            text: {
                                root.i18n.language
                                return root.i18n.columnLabel(parent.display)
                            }
                            color: "#2b2418"
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
                    ScrollBar.horizontal: ScrollBar {}
                    ScrollBar.vertical: ScrollBar {}
                    delegate: Rectangle {
                        implicitWidth: 145
                        implicitHeight: 30
                        color: row % 2 === 0 ? "#fffaf0" : "#f8f1e4"
                        border.color: "#e1d6bd"
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
                objectName: root.objectName + "EmptyState"
                anchors.centerIn: parent
                visible: root.tableModel.totalRows === 0
                text: root.i18n.catalog["common.no_data"]
                color: "#665d50"
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: root.paged
            Button {
                text: root.i18n.catalog["common.previous"]
                enabled: root.tableModel.hasPrevious
                onClicked: root.previousRequested()
            }
            Label {
                text: root.i18n.catalog["common.page"] + " " + root.tableModel.page
                    + " " + root.i18n.catalog["common.of"] + " "
                    + root.tableModel.totalPages + " (" + root.tableModel.totalRows
                    + " " + root.i18n.catalog["common.rows"] + ")"
                color: "#665d50"
            }
            Item { Layout.fillWidth: true }
            Button {
                text: root.i18n.catalog["common.next"]
                enabled: root.tableModel.hasNext
                onClicked: root.nextRequested()
            }
        }
    }
}
