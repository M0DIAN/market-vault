import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    required property var controller
    required property var i18n
    property string tableObjectName: "auditTable"
    function values() { return {symbols: symbols.text, start_date: startDate.text, end_date: endDate.text, calendar_market: calendarMarket.text, calendar_code: calendarCode.text, interval: interval.currentText, session: session.currentText, adjustment: adjustment.currentText} }
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingSm
        Components.PixelPanel {
            id: formPanel
            objectName: root.tableObjectName + "FormPanel"
            Layout.fillWidth: true
            Layout.preferredHeight: formGrid.implicitHeight
                + 2 * (formPanel.padding + 1)
            Layout.minimumHeight: formGrid.implicitHeight
                + 2 * (formPanel.padding + 1)
            GridLayout {
                id: formGrid
                objectName: root.tableObjectName + "FormGrid"
                anchors.fill: parent
                columns: 4
                columnSpacing: Theme.PixelTheme.spacingMd
                rowSpacing: 6
                Components.LabeledTextField { id: symbols; label: root.i18n.catalog["field.symbols"]; text: "US.SPY" }
                Components.PixelDateField { id: startDate; objectName: root.tableObjectName + "StartDate"; label: root.i18n.catalog["field.start_date"]; language: root.i18n.language }
                Components.PixelDateField { id: endDate; objectName: root.tableObjectName + "EndDate"; label: root.i18n.catalog["field.end_date"]; language: root.i18n.language }
                Components.LabeledTextField { id: calendarMarket; label: root.i18n.catalog["field.calendar_market"]; text: "US" }
                Components.LabeledTextField { id: calendarCode; label: root.i18n.catalog["field.calendar_code"] }
                Components.LabeledComboBox { id: interval; label: root.i18n.catalog["field.interval"]; model: ["1m", "5m", "15m", "30m", "60m", "day"] }
                Components.LabeledComboBox { id: session; label: root.i18n.catalog["field.session"]; model: ["ALL", "RTH", "ETH"] }
                Components.LabeledComboBox { id: adjustment; label: root.i18n.catalog["field.adjustment"]; model: ["NONE", "QFQ", "HFQ"] }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Components.PixelButton { text: root.i18n.catalog["audit.run"]; glyph: "audit"; variant: "primary"; enabled: !operationRuntime.busy; onClicked: root.controller.run(root.values()) }
            Components.PixelButton { text: root.i18n.catalog["common.export_csv"]; glyph: "export"; variant: "ghost"; onClicked: exportDialog.open() }
            Components.PixelStatusBadge { status: root.controller.status; text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) } }
            Item { Layout.fillWidth: true }
            Label { text: root.i18n.catalog["common.error"] + ": " + root.controller.error; color: Theme.PixelTheme.vermilionDark; visible: root.controller.error.length > 0; wrapMode: Text.Wrap; Layout.maximumWidth: 380 }
        }
        Components.SummaryStrip { Layout.fillWidth: true; summary: root.controller.summary; i18n: root.i18n }
        Components.DataTable { objectName: root.tableObjectName; Layout.fillWidth: true; Layout.fillHeight: true; tableModel: root.controller.tableModel; i18n: root.i18n }
    }
    Components.SaveExportDialog { id: exportDialog; controller: root.controller; formatName: "csv" }
}
