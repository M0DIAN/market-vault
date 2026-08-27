import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components

Item {
    id: root
    required property var controller
    required property var i18n
    property string tableObjectName: "auditTable"
    function values() { return {symbols: symbols.text, start_date: startDate.text, end_date: endDate.text, calendar_market: calendarMarket.text, calendar_code: calendarCode.text, interval: interval.currentText, session: session.currentText, adjustment: adjustment.currentText} }
    ColumnLayout {
        anchors.fill: parent; spacing: 10
        GridLayout {
            Layout.fillWidth: true; columns: 4; columnSpacing: 10
            Components.LabeledTextField { id: symbols; label: root.i18n.catalog["field.symbols"]; text: "US.SPY" }
            Components.LabeledTextField { id: startDate; label: root.i18n.catalog["field.start_date"] }
            Components.LabeledTextField { id: endDate; label: root.i18n.catalog["field.end_date"] }
            Components.LabeledTextField { id: calendarMarket; label: root.i18n.catalog["field.calendar_market"]; text: "US" }
            Components.LabeledTextField { id: calendarCode; label: root.i18n.catalog["field.calendar_code"] }
            Components.LabeledComboBox { id: interval; label: root.i18n.catalog["field.interval"]; model: ["1m", "5m", "15m", "30m", "60m", "day"] }
            Components.LabeledComboBox { id: session; label: root.i18n.catalog["field.session"]; model: ["ALL", "RTH", "ETH"] }
            Components.LabeledComboBox { id: adjustment; label: root.i18n.catalog["field.adjustment"]; model: ["NONE", "QFQ", "HFQ"] }
        }
        RowLayout {
            Button { text: root.i18n.catalog["audit.run"]; enabled: !operationRuntime.busy; onClicked: root.controller.run(root.values()) }
            Button { text: root.i18n.catalog["common.export_csv"]; onClicked: exportDialog.open() }
            Label { text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) } color: "#665d50" }
            Label { Layout.fillWidth: true; text: root.i18n.catalog["common.error"] + ": " + root.controller.error; color: "#8b2f24"; visible: root.controller.error.length > 0; wrapMode: Text.Wrap }
        }
        Components.SummaryStrip { Layout.fillWidth: true; summary: root.controller.summary; i18n: root.i18n }
        Components.DataTable { objectName: root.tableObjectName; Layout.fillWidth: true; Layout.fillHeight: true; tableModel: root.controller.tableModel; i18n: root.i18n }
    }
    Components.SaveExportDialog { id: exportDialog; controller: root.controller; formatName: "csv" }
}
