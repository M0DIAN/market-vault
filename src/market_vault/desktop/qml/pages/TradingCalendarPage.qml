import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components

Item {
    id: root
    required property var controller
    required property var i18n
    function values() { return {market: scope.currentText === "MARKET" ? market.text : "", code: scope.currentText === "CODE" ? code.text : "", start_date: startDate.text, end_date: endDate.text, page: 1, page_size: Number(pageSize.text)} }
    ColumnLayout {
        anchors.fill: parent; spacing: 10
        GridLayout {
            Layout.fillWidth: true; columns: 5; columnSpacing: 10
            Components.LabeledComboBox { id: scope; label: root.i18n.catalog["field.scope"]; model: ["MARKET", "CODE"] }
            Components.LabeledTextField { id: market; label: root.i18n.catalog["field.market"]; text: "US" }
            Components.LabeledTextField { id: code; label: root.i18n.catalog["field.code"] }
            Components.LabeledTextField { id: startDate; label: root.i18n.catalog["field.start_date"] }
            Components.LabeledTextField { id: endDate; label: root.i18n.catalog["field.end_date"] }
            Components.LabeledTextField { id: pageSize; label: root.i18n.catalog["field.page_size"]; text: "100" }
        }
        RowLayout {
            Button { objectName: "calendarQueryButton"; text: root.i18n.catalog["calendar.local_query"]; enabled: !operationRuntime.busy; onClicked: root.controller.query(root.values()) }
            Button { objectName: "calendarCollectButton"; text: root.i18n.catalog["calendar.fetch"]; enabled: !operationRuntime.busy; onClicked: root.controller.requestCollect(root.values()) }
            Button { text: root.i18n.catalog["common.export_csv"]; onClicked: exportDialog.open() }
            Label { text: root.controller.status; color: "#665d50" }
            Label { text: root.controller.error; color: "#8b2f24"; visible: text.length > 0 }
        }
        Components.SummaryStrip { Layout.fillWidth: true; summary: root.controller.summary; i18n: root.i18n }
        Components.DataTable { objectName: "calendarTable"; Layout.fillWidth: true; Layout.fillHeight: true; tableModel: root.controller.tableModel; i18n: root.i18n; paged: true; onPreviousRequested: root.controller.previousPage(); onNextRequested: root.controller.nextPage() }
    }
    Components.SaveExportDialog { id: exportDialog; controller: root.controller; formatName: "csv" }
    Components.OpenDConfirmDialog { controller: root.controller; i18n: root.i18n }
}
