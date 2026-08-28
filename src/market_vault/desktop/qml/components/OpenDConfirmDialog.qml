import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Dialog {
    id: root
    required property var controller
    required property var i18n
    property string operationName: ""
    property string host: ""
    property int port: 0
    title: i18n.catalog["opend.title"]
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    closePolicy: Popup.CloseOnEscape
    standardButtons: Dialog.NoButton
    padding: Theme.PixelTheme.panelPadding
    header: PixelFrame {
        implicitHeight: 42
        padding: 10
        fillColor: Theme.PixelTheme.goldPale
        borderColor: Theme.PixelTheme.goldDark
        Label {
            anchors.fill: parent
            text: root.title
            color: Theme.PixelTheme.ink
            font.family: Theme.PixelTheme.uiFont
            font.pixelSize: Theme.PixelTheme.fontLg
            font.weight: Font.DemiBold
            verticalAlignment: Text.AlignVCenter
        }
    }
    background: Rectangle {
        color: Theme.PixelTheme.surfaceRaised
        border.color: Theme.PixelTheme.goldDark
        border.width: 2
    }
    contentItem: ColumnLayout {
        spacing: Theme.PixelTheme.spacingMd
        Label {
            Layout.fillWidth: true
            text: root.i18n.catalog["opend.message"]
            color: Theme.PixelTheme.ink
            wrapMode: Text.Wrap
        }
        PixelTag {
            Layout.fillWidth: true
            text: {
                root.i18n.language
                return root.i18n.catalog["opend.operation"] + ": " + root.i18n.operationLabel(root.operationName)
            }
        }
        PixelTag { Layout.fillWidth: true; text: root.i18n.catalog["opend.host"] + ": " + root.host }
        PixelTag { Layout.fillWidth: true; text: root.i18n.catalog["opend.port"] + ": " + root.port }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            PixelButton { text: root.i18n.catalog["common.cancel"]; variant: "secondary"; onClicked: root.reject() }
            PixelButton { text: root.i18n.catalog["common.confirm"]; glyph: "network"; variant: "primary"; onClicked: root.accept() }
        }
    }
    onAccepted: controller.resolveConfirmation(true)
    onRejected: controller.resolveConfirmation(false)
    Connections {
        target: root.controller
        function onConfirmationRequested(operation, host, port) {
            root.operationName = operation
            root.host = host
            root.port = port
            root.open()
        }
    }
}
