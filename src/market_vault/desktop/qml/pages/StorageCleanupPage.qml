import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    required property var controller
    required property var i18n
    ColumnLayout {
        anchors.fill: parent
        spacing: 7

        Components.PixelFrame {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            padding: 9
            fillColor: Theme.PixelTheme.surfaceRaised
            borderColor: Theme.PixelTheme.vermilion
            accentColor: Theme.PixelTheme.vermilion
            accented: true
            RowLayout {
                anchors.fill: parent
                spacing: 8
                Components.PixelGlyph { glyph: "lock"; color: Theme.PixelTheme.vermilionDark; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                Label { Layout.fillWidth: true; text: root.i18n.catalog["storage.warning"]; color: Theme.PixelTheme.vermilionDark; wrapMode: Text.Wrap; font.weight: Font.DemiBold; font.pixelSize: Theme.PixelTheme.fontSm }
            }
        }

        Components.PixelPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: 116
            GridLayout {
                anchors.fill: parent
                columns: 4
                uniformCellWidths: true
                columnSpacing: Theme.PixelTheme.spacingMd
                rowSpacing: 6
                Components.LabeledTextField { label: root.i18n.catalog["field.source"]; text: root.controller.scope.source; onEdited: value => root.controller.setScopeField("source", value) }
                Components.LabeledTextField { id: storageSymbols; objectName: "storageSymbols"; label: root.i18n.catalog["field.symbols"]; text: root.controller.scope.symbols; onEdited: value => root.controller.setScopeField("symbols", value) }
                Components.PixelDateField { objectName: "storageStartDate"; label: root.i18n.catalog["field.start_date"]; language: root.i18n.language; text: root.controller.scope.start_date; onEdited: value => root.controller.setScopeField("start_date", value) }
                Components.PixelDateField { objectName: "storageEndDate"; label: root.i18n.catalog["field.end_date"]; language: root.i18n.language; text: root.controller.scope.end_date; onEdited: value => root.controller.setScopeField("end_date", value) }
                Components.LabeledTextField { label: root.i18n.catalog["field.interval"]; text: root.controller.scope.interval; onEdited: value => root.controller.setScopeField("interval", value) }
                Components.LabeledTextField { label: root.i18n.catalog["field.session"]; text: root.controller.scope.session; onEdited: value => root.controller.setScopeField("session", value) }
                Components.LabeledTextField { label: root.i18n.catalog["field.adjustment"]; text: root.controller.scope.adjustment; onEdited: value => root.controller.setScopeField("adjustment", value) }
                Components.LabeledTextField { label: root.i18n.catalog["field.source_schema_version"]; text: root.controller.scope.source_schema_version; onEdited: value => root.controller.setScopeField("source_schema_version", value) }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Components.PixelButton { objectName: "storageReviewButton"; text: root.i18n.catalog["storage.review"]; glyph: "audit"; variant: "primary"; enabled: !operationRuntime.busy; onClicked: root.controller.review() }
            Components.PixelTag { text: root.i18n.catalog["storage.plan_id"] + ": " + (root.controller.planId || "-") }
            Components.PixelStatusBadge { status: root.controller.planStatus; text: { root.i18n.language; return root.i18n.statusLabel(root.controller.planStatus) } }
            Item { Layout.fillWidth: true }
        }

        Components.SummaryStrip { Layout.fillWidth: true; summary: root.controller.summary; i18n: root.i18n }

        ColumnLayout {
            Layout.fillWidth: true
            visible: root.controller.refusalReasons.length > 0
            spacing: 2
            Label { text: root.i18n.catalog["storage.refusals"]; color: Theme.PixelTheme.vermilionDark; font.weight: Font.DemiBold }
            Repeater {
                model: root.controller.refusalReasons
                Label { required property var modelData; Layout.fillWidth: true; text: modelData.code + ": " + JSON.stringify(modelData); color: Theme.PixelTheme.vermilionDark; wrapMode: Text.Wrap }
            }
        }

        Components.DataTable { objectName: "storageReviewTable"; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 110; tableModel: root.controller.tableModel; i18n: root.i18n }

        Label { Layout.fillWidth: true; text: root.i18n.catalog["storage.confirmation_help"]; color: Theme.PixelTheme.inkMuted; wrapMode: Text.Wrap; font.pixelSize: Theme.PixelTheme.fontSm }
        RowLayout {
            Layout.fillWidth: true
            Components.PixelTextField { objectName: "storageConfirmation"; Layout.fillWidth: true; activeFocusOnTab: true; text: root.controller.confirmation; placeholderText: "PURGE <plan_id>"; onTextEdited: root.controller.setConfirmation(text) }
            Components.PixelButton { objectName: "storageExecuteButton"; text: root.i18n.catalog["storage.execute"]; glyph: "lock"; variant: "danger"; enabled: root.controller.executeEnabled && !operationRuntime.busy; onClicked: root.controller.execute_purge(root.controller.planId, root.controller.confirmation) }
        }
        Label { Layout.fillWidth: true; text: root.i18n.catalog["common.error"] + ": " + root.controller.error; color: Theme.PixelTheme.vermilionDark; visible: root.controller.error.length > 0; wrapMode: Text.Wrap }
    }
}
