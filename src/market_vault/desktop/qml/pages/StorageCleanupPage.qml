import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components

Item {
    id: root
    required property var controller
    required property var i18n
    ColumnLayout {
        anchors.fill: parent; spacing: 10
        Label { Layout.fillWidth: true; text: root.i18n.catalog["storage.warning"]; color: "#8b2f24"; wrapMode: Text.Wrap; font.weight: Font.DemiBold }
        GridLayout {
            Layout.fillWidth: true; columns: 4; columnSpacing: 10
            Components.LabeledTextField { label: root.i18n.catalog["field.source"]; text: root.controller.scope.source; onEdited: value => root.controller.setScopeField("source", value) }
            Components.LabeledTextField { id: storageSymbols; objectName: "storageSymbols"; label: root.i18n.catalog["field.symbols"]; text: root.controller.scope.symbols; onEdited: value => root.controller.setScopeField("symbols", value) }
            Components.LabeledTextField { label: root.i18n.catalog["field.start_date"]; text: root.controller.scope.start_date; onEdited: value => root.controller.setScopeField("start_date", value) }
            Components.LabeledTextField { label: root.i18n.catalog["field.end_date"]; text: root.controller.scope.end_date; onEdited: value => root.controller.setScopeField("end_date", value) }
            Components.LabeledTextField { label: root.i18n.catalog["field.interval"]; text: root.controller.scope.interval; onEdited: value => root.controller.setScopeField("interval", value) }
            Components.LabeledTextField { label: root.i18n.catalog["field.session"]; text: root.controller.scope.session; onEdited: value => root.controller.setScopeField("session", value) }
            Components.LabeledTextField { label: root.i18n.catalog["field.adjustment"]; text: root.controller.scope.adjustment; onEdited: value => root.controller.setScopeField("adjustment", value) }
            Components.LabeledTextField { label: root.i18n.catalog["field.source_schema_version"]; text: root.controller.scope.source_schema_version; onEdited: value => root.controller.setScopeField("source_schema_version", value) }
        }
        RowLayout {
            Button { objectName: "storageReviewButton"; text: root.i18n.catalog["storage.review"]; enabled: !operationRuntime.busy; onClicked: root.controller.review() }
            Label { text: root.i18n.catalog["storage.plan_id"] + ": " + (root.controller.planId || "-"); color: "#665d50" }
            Label { text: root.controller.planStatus; color: "#665d50" }
        }
        Components.SummaryStrip { Layout.fillWidth: true; summary: root.controller.summary; i18n: root.i18n }
        ColumnLayout {
            Layout.fillWidth: true
            visible: root.controller.refusalReasons.length > 0
            Label { text: root.i18n.catalog["storage.refusals"]; color: "#8b2f24"; font.weight: Font.DemiBold }
            Repeater {
                model: root.controller.refusalReasons
                Label {
                    required property var modelData
                    Layout.fillWidth: true
                    text: modelData.code + ": " + JSON.stringify(modelData)
                    color: "#8b2f24"
                    wrapMode: Text.Wrap
                }
            }
        }
        Components.DataTable { objectName: "storageReviewTable"; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 130; tableModel: root.controller.tableModel; i18n: root.i18n }
        Label { Layout.fillWidth: true; text: root.i18n.catalog["storage.confirmation_help"]; color: "#665d50"; wrapMode: Text.Wrap }
        RowLayout {
            TextField { objectName: "storageConfirmation"; Layout.fillWidth: true; text: root.controller.confirmation; placeholderText: "PURGE <plan_id>"; onTextEdited: root.controller.setConfirmation(text) }
            Button { objectName: "storageExecuteButton"; text: root.i18n.catalog["storage.execute"]; enabled: root.controller.executeEnabled && !operationRuntime.busy; onClicked: root.controller.execute_purge(root.controller.planId, root.controller.confirmation) }
        }
        Label { Layout.fillWidth: true; text: root.controller.error; color: "#8b2f24"; visible: text.length > 0; wrapMode: Text.Wrap }
    }
}
