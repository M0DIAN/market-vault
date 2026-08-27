import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components

Item {
    id: root
    required property var controller
    required property var i18n

    function values() {
        return {
            symbols: symbols.text, start_date: startDate.text, end_date: endDate.text,
            bootstrap_start_date: bootstrapDate.text, calendar_market: calendarMarket.text,
            calendar_code: calendarCode.text, interval: interval.currentText,
            session: session.currentText, adjustment: adjustment.currentText,
            max_retries: retries.text, retry_backoff_seconds: backoff.text,
            force: force.checked, incremental: incremental.checked
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        GridLayout {
            Layout.fillWidth: true
            columns: 4
            columnSpacing: 10
            rowSpacing: 7
            Components.LabeledTextField { id: symbols; objectName: "backfillSymbols"; label: root.i18n.catalog["field.symbols"]; text: "US.SPY" }
            Components.LabeledTextField { id: startDate; label: root.i18n.catalog["field.start_date"] }
            Components.LabeledTextField { id: endDate; label: root.i18n.catalog["field.end_date"] }
            Components.LabeledTextField { id: bootstrapDate; label: root.i18n.catalog["field.bootstrap_start_date"] }
            Components.LabeledTextField { id: calendarMarket; label: root.i18n.catalog["field.calendar_market"]; text: "US" }
            Components.LabeledTextField { id: calendarCode; label: root.i18n.catalog["field.calendar_code"] }
            Components.LabeledComboBox { id: interval; label: root.i18n.catalog["field.interval"]; model: ["1m", "5m", "15m", "30m", "60m", "day"] }
            Components.LabeledComboBox { id: session; label: root.i18n.catalog["field.session"]; model: ["ALL", "RTH", "ETH"] }
            Components.LabeledComboBox { id: adjustment; label: root.i18n.catalog["field.adjustment"]; model: ["NONE", "QFQ", "HFQ"] }
            Components.LabeledTextField { id: retries; label: root.i18n.catalog["field.max_retries"]; text: "2" }
            Components.LabeledTextField { id: backoff; label: root.i18n.catalog["field.retry_backoff"]; text: "2.0" }
            RowLayout { CheckBox { id: force; text: root.i18n.catalog["field.force"] } CheckBox { id: incremental; text: root.i18n.catalog["field.incremental"] } }
        }
        RowLayout {
            Button { objectName: "backfillPlanButton"; text: root.i18n.catalog["historical.plan"]; enabled: !operationRuntime.busy; onClicked: root.controller.plan(root.values()) }
            Button { objectName: "backfillExecuteButton"; text: root.i18n.catalog["historical.execute"]; enabled: !operationRuntime.busy; onClicked: root.controller.requestExecute(root.values()) }
            Label { text: root.controller.status; color: "#665d50" }
            Label { text: root.controller.error; color: "#8b2f24"; visible: text.length > 0 }
        }
        Components.SummaryStrip { Layout.fillWidth: true; summary: root.controller.summary; i18n: root.i18n }
        Components.DataTable { objectName: "backfillPlanTable"; Layout.fillWidth: true; Layout.fillHeight: true; tableModel: root.controller.tableModel; i18n: root.i18n }
    }
    Components.OpenDConfirmDialog { controller: root.controller; i18n: root.i18n }
}
