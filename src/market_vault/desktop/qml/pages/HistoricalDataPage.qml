import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

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
        spacing: Theme.PixelTheme.spacingSm

        Components.PixelPanel {
            id: formPanel
            objectName: "historicalDataFormPanel"
            Layout.fillWidth: true
            Layout.preferredHeight: formGrid.implicitHeight
                + 2 * (formPanel.padding + 1)
            Layout.minimumHeight: formGrid.implicitHeight
                + 2 * (formPanel.padding + 1)
            enabled: !root.controller.confirmationPending
            opacity: enabled ? 1 : Theme.PixelTheme.disabledOpacity
            GridLayout {
                id: formGrid
                objectName: "historicalDataFormGrid"
                anchors.fill: parent
                columns: 4
                columnSpacing: Theme.PixelTheme.spacingMd
                rowSpacing: 6
                Components.LabeledTextField { id: symbols; objectName: "backfillSymbols"; label: root.i18n.catalog["field.symbols"]; text: "US.SPY" }
                Components.PixelDateField { id: startDate; objectName: "backfillStartDate"; label: root.i18n.catalog["field.start_date"]; language: root.i18n.language }
                Components.PixelDateField { id: endDate; objectName: "backfillEndDate"; label: root.i18n.catalog["field.end_date"]; language: root.i18n.language }
                Components.PixelDateField { id: bootstrapDate; objectName: "backfillBootstrapDate"; label: root.i18n.catalog["field.bootstrap_start_date"]; language: root.i18n.language }
                Components.LabeledTextField { id: calendarMarket; label: root.i18n.catalog["field.calendar_market"]; text: "US" }
                Components.LabeledTextField { id: calendarCode; label: root.i18n.catalog["field.calendar_code"] }
                Components.LabeledComboBox { id: interval; label: root.i18n.catalog["field.interval"]; model: ["1m", "5m", "15m", "30m", "60m", "day"] }
                Components.LabeledComboBox { id: session; label: root.i18n.catalog["field.session"]; model: ["ALL", "RTH", "ETH"] }
                Components.LabeledComboBox { id: adjustment; label: root.i18n.catalog["field.adjustment"]; model: ["NONE", "QFQ", "HFQ"] }
                Components.LabeledTextField { id: retries; label: root.i18n.catalog["field.max_retries"]; text: "2" }
                Components.LabeledTextField { id: backoff; label: root.i18n.catalog["field.retry_backoff"]; text: "2.0" }
                Item { Layout.preferredWidth: Theme.PixelTheme.formFieldWidth; Layout.preferredHeight: 1 }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.columnSpan: 4
                    Layout.topMargin: 4
                    Layout.alignment: Qt.AlignVCenter
                    spacing: Theme.PixelTheme.spacingLg
                    Components.PixelCheckBox { id: force; objectName: "backfillForce"; Layout.alignment: Qt.AlignVCenter; text: root.i18n.catalog["field.force"] }
                    Components.PixelCheckBox { id: incremental; objectName: "backfillIncremental"; Layout.alignment: Qt.AlignVCenter; text: root.i18n.catalog["field.incremental"] }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.PixelTheme.spacingSm
            Components.PixelButton {
                objectName: "backfillPlanButton"
                text: root.i18n.catalog["historical.plan"]
                glyph: "history"
                variant: "primary"
                enabled: !operationRuntime.busy
                onClicked: root.controller.plan(root.values())
            }
            Components.PixelButton {
                objectName: "backfillExecuteButton"
                text: root.i18n.catalog["historical.execute"]
                glyph: "network"
                variant: "secondary"
                enabled: !operationRuntime.busy && !root.controller.confirmationPending
                onClicked: root.controller.requestExecute(root.values())
            }
            Components.PixelStatusBadge {
                status: root.controller.status
                text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) }
            }
            Item { Layout.fillWidth: true }
            Label {
                text: root.i18n.catalog["common.error"] + ": " + root.controller.error
                color: Theme.PixelTheme.vermilionDark
                visible: root.controller.error.length > 0
                wrapMode: Text.Wrap
                Layout.maximumWidth: 420
            }
        }

        Components.SummaryStrip { Layout.fillWidth: true; summary: root.controller.summary; i18n: root.i18n }
        Components.DataTable {
            objectName: "backfillPlanTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            tableModel: root.controller.tableModel
            i18n: root.i18n
        }
    }
    Components.OpenDConfirmDialog { controller: root.controller; i18n: root.i18n }
}
