import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components

Item {
    id: root
    required property var controller
    required property var i18n
    function values() { return {code: code.text, start_date: startDate.text, end_date: endDate.text, interval: interval.currentText, requested_session: requestedSession.currentText, bar_session: barSession.currentText, adjustment: adjustment.currentText, page: 1, page_size: Number(pageSize.text)} }
    ColumnLayout {
        anchors.fill: parent; spacing: 10
        GridLayout {
            Layout.fillWidth: true; columns: 4; columnSpacing: 10
            Components.LabeledTextField { id: code; objectName: "marketDataCode"; label: root.i18n.catalog["field.code"]; text: "US.SPY" }
            Components.LabeledTextField { id: startDate; objectName: "marketDataStartDate"; label: root.i18n.catalog["field.start_date"] }
            Components.LabeledTextField { id: endDate; label: root.i18n.catalog["field.end_date"] }
            Components.LabeledComboBox { id: interval; label: root.i18n.catalog["field.interval"]; model: ["1m", "5m", "15m", "30m", "60m", "day"] }
            Components.LabeledComboBox { id: requestedSession; label: root.i18n.catalog["field.requested_session"]; model: ["", "ALL", "RTH", "ETH"] }
            Components.LabeledComboBox { id: barSession; label: root.i18n.catalog["field.bar_session"]; model: ["", "OVERNIGHT", "PRE_MARKET", "REGULAR", "AFTER_HOURS"] }
            Components.LabeledComboBox { id: adjustment; label: root.i18n.catalog["field.adjustment"]; model: ["NONE", "QFQ", "HFQ"] }
            Components.LabeledTextField { id: pageSize; label: root.i18n.catalog["field.page_size"]; text: "100" }
        }
        RowLayout {
            Button { objectName: "marketDataQueryButton"; text: root.i18n.catalog["market.query"]; enabled: !operationRuntime.busy; onClicked: root.controller.query(root.values()) }
            Button { text: root.i18n.catalog["common.export_csv"]; onClicked: csvDialog.open() }
            Button { text: root.i18n.catalog["common.export_json"]; onClicked: jsonDialog.open() }
            Label { text: root.controller.status; color: "#665d50" }
            Label { text: root.controller.error; color: "#8b2f24"; visible: text.length > 0 }
        }
        Components.DataTable { objectName: "marketDataTable"; Layout.fillWidth: true; Layout.fillHeight: true; tableModel: root.controller.tableModel; i18n: root.i18n; paged: true; onPreviousRequested: root.controller.previousPage(); onNextRequested: root.controller.nextPage() }
    }
    Components.SaveExportDialog { id: csvDialog; controller: root.controller; formatName: "csv" }
    Components.SaveExportDialog { id: jsonDialog; controller: root.controller; formatName: "json" }
}
