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
        return {market: scope.currentText === "MARKET" ? market.text : "",
            code: scope.currentText === "CODE" ? code.text : "",
            start_date: startDate.text, end_date: endDate.text,
            page: 1, page_size: Number(pageSize.text)}
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingSm
        Components.PixelPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: 116
            enabled: !root.controller.confirmationPending
            opacity: enabled ? 1 : Theme.PixelTheme.disabledOpacity
            GridLayout {
                anchors.fill: parent
                columns: 3
                uniformCellWidths: true
                columnSpacing: Theme.PixelTheme.spacingMd
                rowSpacing: 6
                Components.LabeledComboBox { id: scope; label: root.i18n.catalog["field.scope"]; model: ["MARKET", "CODE"] }
                Components.LabeledTextField { id: market; label: root.i18n.catalog["field.market"]; text: "US" }
                Components.LabeledTextField { id: code; label: root.i18n.catalog["field.code"] }
                Components.LabeledTextField { id: startDate; label: root.i18n.catalog["field.start_date"] }
                Components.LabeledTextField { id: endDate; label: root.i18n.catalog["field.end_date"] }
                Components.LabeledTextField { id: pageSize; label: root.i18n.catalog["field.page_size"]; text: "100" }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Components.PixelButton { objectName: "calendarQueryButton"; text: root.i18n.catalog["calendar.local_query"]; glyph: "calendar"; variant: "primary"; enabled: !operationRuntime.busy; onClicked: root.controller.query(root.values()) }
            Components.PixelButton { objectName: "calendarCollectButton"; text: root.i18n.catalog["calendar.fetch"]; glyph: "network"; enabled: !operationRuntime.busy && !root.controller.confirmationPending; onClicked: root.controller.requestCollect(root.values()) }
            Components.PixelButton { text: root.i18n.catalog["common.export_csv"]; glyph: "export"; variant: "ghost"; onClicked: exportDialog.open() }
            Components.PixelStatusBadge { status: root.controller.status; text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) } }
            Item { Layout.fillWidth: true }
            Label { text: root.i18n.catalog["common.error"] + ": " + root.controller.error; color: Theme.PixelTheme.vermilionDark; visible: root.controller.error.length > 0; wrapMode: Text.Wrap; Layout.maximumWidth: 380 }
        }
        Components.SummaryStrip { Layout.fillWidth: true; summary: root.controller.summary; i18n: root.i18n }
        Components.DataTable { objectName: "calendarTable"; Layout.fillWidth: true; Layout.fillHeight: true; tableModel: root.controller.tableModel; i18n: root.i18n; paged: true; onPreviousRequested: root.controller.previousPage(); onNextRequested: root.controller.nextPage() }
    }
    Components.SaveExportDialog { id: exportDialog; controller: root.controller; formatName: "csv" }
    Components.OpenDConfirmDialog { controller: root.controller; i18n: root.i18n }
}
