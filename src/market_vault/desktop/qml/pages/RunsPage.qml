import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components

Item {
    id: root
    required property var controller
    required property var i18n
    function values() { return {status: status.currentText, dataset: dataset.text, page: 1, page_size: Number(pageSize.text)} }
    ColumnLayout {
        anchors.fill: parent; spacing: 10
        GridLayout {
            Layout.fillWidth: true; columns: 3; columnSpacing: 10
            Components.LabeledComboBox { id: status; label: root.i18n.catalog["field.status"]; model: ["", "RUNNING", "SUCCESS", "PARTIAL", "FAILED"] }
            Components.LabeledTextField { id: dataset; label: root.i18n.catalog["field.dataset"] }
            Components.LabeledTextField { id: pageSize; label: root.i18n.catalog["field.page_size"]; text: "100" }
        }
        RowLayout {
            Button { text: root.i18n.catalog["runs.refresh"]; enabled: !operationRuntime.busy; onClicked: root.controller.refresh(root.values()) }
            Button { text: root.i18n.catalog["common.export_csv"]; onClicked: exportDialog.open() }
            Label { text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) } color: "#665d50" }
            Label { Layout.fillWidth: true; text: root.i18n.catalog["common.error"] + ": " + root.controller.error; color: "#8b2f24"; visible: root.controller.error.length > 0; wrapMode: Text.Wrap }
        }
        Components.DataTable { objectName: "runsTable"; Layout.fillWidth: true; Layout.fillHeight: true; tableModel: root.controller.tableModel; i18n: root.i18n; paged: true; onPreviousRequested: root.controller.previousPage(); onNextRequested: root.controller.nextPage() }
    }
    Components.SaveExportDialog { id: exportDialog; controller: root.controller; formatName: "csv" }
}
