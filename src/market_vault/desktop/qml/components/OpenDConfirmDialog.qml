import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: root
    required property var controller
    required property var i18n
    property string operationName: ""
    property string host: ""
    property int port: 0
    title: i18n.catalog["opend.title"]
    modal: true
    standardButtons: Dialog.Ok | Dialog.Cancel
    onAccepted: controller.resolveConfirmation(true)
    onRejected: controller.resolveConfirmation(false)
    contentItem: ColumnLayout {
        spacing: 8
        Label { text: root.i18n.catalog["opend.message"]; wrapMode: Text.Wrap }
        Label { text: root.i18n.catalog["opend.operation"] + ": " + root.operationName }
        Label { text: root.i18n.catalog["opend.host"] + ": " + root.host }
        Label { text: root.i18n.catalog["opend.port"] + ": " + root.port }
    }
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
