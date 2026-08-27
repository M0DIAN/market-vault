import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components

Item {
    id: root
    required property var controller
    required property var i18n
    function values() { return {symbols: symbols.text, start_date: startDate.text, end_date: endDate.text, interval: interval.text, session: session.text, adjustment: adjustment.text} }
    ColumnLayout {
        anchors.fill: parent; spacing: 10
        GridLayout {
            Layout.fillWidth: true; columns: 3; columnSpacing: 10
            Components.LabeledTextField { id: symbols; label: root.i18n.catalog["field.symbols"] }
            Components.LabeledTextField { id: startDate; label: root.i18n.catalog["field.start_date"] }
            Components.LabeledTextField { id: endDate; label: root.i18n.catalog["field.end_date"] }
            Components.LabeledTextField { id: interval; label: root.i18n.catalog["field.interval"] }
            Components.LabeledTextField { id: session; label: root.i18n.catalog["field.session"] }
            Components.LabeledTextField { id: adjustment; label: root.i18n.catalog["field.adjustment"] }
        }
        RowLayout {
            Button { text: root.i18n.catalog["inventory.inspect"]; enabled: !operationRuntime.busy; onClicked: root.controller.refresh(root.values()) }
            Button { text: root.i18n.catalog["common.export_csv"]; onClicked: exportDialog.open() }
            Label { text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) } color: "#665d50" }
            Label { Layout.fillWidth: true; text: root.i18n.catalog["common.error"] + ": " + root.controller.error; color: "#8b2f24"; visible: root.controller.error.length > 0; wrapMode: Text.Wrap }
        }
        Components.SummaryStrip { Layout.fillWidth: true; summary: root.controller.summary; i18n: root.i18n }
        Components.DataTable { objectName: "inventoryTable"; Layout.fillWidth: true; Layout.fillHeight: true; tableModel: root.controller.tableModel; i18n: root.i18n }
    }
    Components.SaveExportDialog { id: exportDialog; controller: root.controller; formatName: "csv" }
}
