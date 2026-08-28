import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    required property var controller
    required property var i18n
    function values() { return {status: status.currentText, dataset: dataset.text, page: 1, page_size: Number(pageSize.text)} }
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingSm
        Components.PixelPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: 68
            GridLayout {
                anchors.fill: parent
                columns: 3
                uniformCellWidths: true
                columnSpacing: Theme.PixelTheme.spacingMd
                Components.LabeledComboBox { id: status; label: root.i18n.catalog["field.status"]; model: ["", "RUNNING", "SUCCESS", "PARTIAL", "FAILED"] }
                Components.LabeledTextField { id: dataset; label: root.i18n.catalog["field.dataset"] }
                Components.LabeledTextField { id: pageSize; label: root.i18n.catalog["field.page_size"]; text: "100" }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Components.PixelButton { text: root.i18n.catalog["runs.refresh"]; glyph: "refresh"; variant: "primary"; enabled: !operationRuntime.busy; onClicked: root.controller.refresh(root.values()) }
            Components.PixelButton { text: root.i18n.catalog["common.export_csv"]; glyph: "export"; variant: "ghost"; onClicked: exportDialog.open() }
            Components.PixelStatusBadge { status: root.controller.status; text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) } }
            Item { Layout.fillWidth: true }
            Label { text: root.i18n.catalog["common.error"] + ": " + root.controller.error; color: Theme.PixelTheme.vermilionDark; visible: root.controller.error.length > 0; wrapMode: Text.Wrap; Layout.maximumWidth: 380 }
        }
        Components.DataTable { objectName: "runsTable"; Layout.fillWidth: true; Layout.fillHeight: true; tableModel: root.controller.tableModel; i18n: root.i18n; paged: true; onPreviousRequested: root.controller.previousPage(); onNextRequested: root.controller.nextPage() }
    }
    Components.SaveExportDialog { id: exportDialog; controller: root.controller; formatName: "csv" }
}
