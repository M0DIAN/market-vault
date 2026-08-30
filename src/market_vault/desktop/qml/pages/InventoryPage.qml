import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    required property var controller
    required property var i18n
    function values() { return {symbols: symbols.text, start_date: startDate.text, end_date: endDate.text, interval: interval.text, session: session.text, adjustment: adjustment.text} }
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingSm
        Components.PixelPanel {
            id: formPanel
            objectName: "inventoryFormPanel"
            Layout.fillWidth: true
            Layout.preferredHeight: formGrid.implicitHeight
                + 2 * (formPanel.padding + 1)
            Layout.minimumHeight: formGrid.implicitHeight
                + 2 * (formPanel.padding + 1)
            GridLayout {
                id: formGrid
                objectName: "inventoryFormGrid"
                anchors.fill: parent
                columns: 3
                uniformCellWidths: true
                columnSpacing: Theme.PixelTheme.spacingMd
                rowSpacing: 6
                Components.LabeledTextField { id: symbols; label: root.i18n.catalog["field.symbols"] }
                Components.PixelDateField { id: startDate; objectName: "inventoryStartDate"; label: root.i18n.catalog["field.start_date"]; language: root.i18n.language }
                Components.PixelDateField { id: endDate; objectName: "inventoryEndDate"; label: root.i18n.catalog["field.end_date"]; language: root.i18n.language }
                Components.LabeledTextField { id: interval; label: root.i18n.catalog["field.interval"] }
                Components.LabeledTextField { id: session; label: root.i18n.catalog["field.session"] }
                Components.LabeledTextField { id: adjustment; label: root.i18n.catalog["field.adjustment"] }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Components.PixelButton { text: root.i18n.catalog["inventory.inspect"]; glyph: "inventory"; variant: "primary"; enabled: !operationRuntime.busy; onClicked: root.controller.refresh(root.values()) }
            Components.PixelButton { text: root.i18n.catalog["common.export_csv"]; glyph: "export"; variant: "ghost"; onClicked: exportDialog.open() }
            Components.PixelStatusBadge { status: root.controller.status; text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) } }
            Item { Layout.fillWidth: true }
            Label { text: root.i18n.catalog["common.error"] + ": " + root.controller.error; color: Theme.PixelTheme.vermilionDark; visible: root.controller.error.length > 0; wrapMode: Text.Wrap; Layout.maximumWidth: 380 }
        }
        Components.SummaryStrip { Layout.fillWidth: true; summary: root.controller.summary; i18n: root.i18n }
        Components.DataTable { objectName: "inventoryTable"; Layout.fillWidth: true; Layout.fillHeight: true; tableModel: root.controller.tableModel; i18n: root.i18n }
    }
    Components.SaveExportDialog { id: exportDialog; controller: root.controller; formatName: "csv" }
}
