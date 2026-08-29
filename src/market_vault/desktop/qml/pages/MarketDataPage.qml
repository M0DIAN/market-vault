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
        return {code: code.text, start_date: startDate.text, end_date: endDate.text,
            interval: interval.currentText, requested_session: requestedSession.currentText,
            bar_session: barSession.currentText, adjustment: adjustment.currentText,
            page: 1, page_size: Number(pageSize.text)}
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingSm
        Components.PixelPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: 116
            GridLayout {
                anchors.fill: parent
                columns: 4
                uniformCellWidths: true
                columnSpacing: Theme.PixelTheme.spacingMd
                rowSpacing: 6
                Components.LabeledTextField { id: code; objectName: "marketDataCode"; label: root.i18n.catalog["field.code"]; text: "US.SPY" }
                Components.PixelDateField { id: startDate; objectName: "marketDataStartDate"; label: root.i18n.catalog["field.start_date"]; language: root.i18n.language }
                Components.PixelDateField { id: endDate; objectName: "marketDataEndDate"; label: root.i18n.catalog["field.end_date"]; language: root.i18n.language }
                Components.LabeledComboBox { id: interval; label: root.i18n.catalog["field.interval"]; model: ["1m", "5m", "15m", "30m", "60m", "day"] }
                Components.LabeledComboBox { id: requestedSession; label: root.i18n.catalog["field.requested_session"]; model: ["", "ALL", "RTH", "ETH"] }
                Components.LabeledComboBox { id: barSession; label: root.i18n.catalog["field.bar_session"]; model: ["", "OVERNIGHT", "PRE_MARKET", "REGULAR", "AFTER_HOURS"] }
                Components.LabeledComboBox { id: adjustment; label: root.i18n.catalog["field.adjustment"]; model: ["NONE", "QFQ", "HFQ"] }
                Components.LabeledTextField { id: pageSize; label: root.i18n.catalog["field.page_size"]; text: "100" }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Components.PixelButton { objectName: "marketDataQueryButton"; text: root.i18n.catalog["market.query"]; glyph: "chart"; variant: "primary"; enabled: !operationRuntime.busy; onClicked: root.controller.query(root.values()) }
            Components.PixelButton { text: root.i18n.catalog["common.export_csv"]; glyph: "export"; variant: "ghost"; onClicked: csvDialog.open() }
            Components.PixelButton { text: root.i18n.catalog["common.export_json"]; glyph: "export"; variant: "ghost"; onClicked: jsonDialog.open() }
            Components.PixelStatusBadge { status: root.controller.status; text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) } }
            Item { Layout.fillWidth: true }
            Label { text: root.i18n.catalog["common.error"] + ": " + root.controller.error; color: Theme.PixelTheme.vermilionDark; visible: root.controller.error.length > 0; wrapMode: Text.Wrap; Layout.maximumWidth: 380 }
        }
        Components.DataTable { objectName: "marketDataTable"; Layout.fillWidth: true; Layout.fillHeight: true; tableModel: root.controller.tableModel; i18n: root.i18n; paged: true; onPreviousRequested: root.controller.previousPage(); onNextRequested: root.controller.nextPage() }
    }
    Components.SaveExportDialog { id: csvDialog; controller: root.controller; formatName: "csv" }
    Components.SaveExportDialog { id: jsonDialog; controller: root.controller; formatName: "json" }
}
