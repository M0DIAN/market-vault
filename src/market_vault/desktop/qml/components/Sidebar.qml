import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: sidebar
    required property var shell
    required property var i18n
    color: "#fbf5e9"
    border.color: "#d8c9a6"
    border.width: 1

    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true

        Column {
            width: parent.width
            topPadding: 12
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
                        color: "#8b7a59"
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                    }

                    Button {
                        id: navigationButton
                        objectName: "nav_" + modelData.id
                        width: parent.width
                        height: 38
                        text: sidebar.i18n.catalog[modelData.labelKey]
                        checkable: true
                        checked: sidebar.shell.currentPage === modelData.id
                        onClicked: sidebar.shell.selectPage(modelData.id)

                        contentItem: Label {
                            text: navigationButton.text
                            color: navigationButton.checked ? "#2b2418" : "#665d50"
                            font.pixelSize: 13
                            font.weight: navigationButton.checked
                                ? Font.DemiBold
                                : Font.Normal
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: 18
                            elide: Text.ElideRight
                        }

                        background: Rectangle {
                            color: navigationButton.checked
                                ? "#eee1bf"
                                : (navigationButton.hovered ? "#f4ead5" : "transparent")
                            border.color: navigationButton.checked
                                ? "#c59a3d"
                                : "transparent"
                            border.width: 1
                        }
                    }
                }
            }
        }
    }
}
