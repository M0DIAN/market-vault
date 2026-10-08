import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    required property var controller
    required property var i18n
    property bool showPreview: false
    property var pendingBuild: ({})

    function values() {
        return {"symbol": symbol.text, "start_date": startDate.text, "end_date": endDate.text,
                "interval": interval.currentText, "preset": preset.currentText,
                "stride_bars": stride.text, "target_horizon_bars": horizon.text}
    }
    FileDialog {
        id: saveDialog
        objectName: "intradaySaveDialog"
        title: root.i18n.catalog["quant.intraday_build"]
        fileMode: FileDialog.SaveFile
        nameFilters: ["JSON (*.json)"]
        defaultSuffix: "json"
        onAccepted: {
            root.showPreview = false
            root.controller.buildIntraday(root.pendingBuild, selectedFile.toString())
        }
    }
    FileDialog {
        id: openDialog
        objectName: "intradayOpenDialog"
        title: root.i18n.catalog["quant.intraday_open"]
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON (*.json)"]
        onAccepted: {
            root.showPreview = false
            root.controller.inspectIntraday(selectedFile.toString())
        }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingSm
        Components.PixelPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: 168
            padding: Theme.PixelTheme.panelPadding
            GridLayout {
                anchors.fill: parent
                columns: 4
                columnSpacing: Theme.PixelTheme.spacingMd
                Components.LabeledTextField {
                    id: symbol
                    objectName: "intradaySymbol"
                    label: root.i18n.catalog["quant.builder_symbol"]
                    text: "US.SPY"
                }
                Components.PixelDateField {
                    id: startDate
                    objectName: "intradayStartDate"
                    label: root.i18n.catalog["field.start_date"]
                    language: root.i18n.language
                }
                Components.PixelDateField {
                    id: endDate
                    objectName: "intradayEndDate"
                    label: root.i18n.catalog["field.end_date"]
                    language: root.i18n.language
                }
                Components.LabeledComboBox {
                    id: interval
                    objectName: "intradayInterval"
                    label: root.i18n.catalog["field.interval"]
                    model: ["5m", "1m", "15m", "30m"]
                }
                Components.LabeledComboBox {
                    id: preset
                    objectName: "intradayPreset"
                    label: root.i18n.catalog["quant.builder_preset"]
                    model: ["LIGHT_TECHNICAL", "CORE_TECHNICAL"]
                }
                Components.LabeledTextField {
                    id: stride
                    objectName: "intradayStride"
                    label: root.i18n.catalog["quant.intraday_stride"]
                    text: "1"
                }
                Components.LabeledTextField {
                    id: horizon
                    objectName: "intradayHorizon"
                    label: root.i18n.catalog["quant.intraday_horizon"]
                    text: "3"
                }
                Components.PixelTag { text: "TS2 / RTH / NONE" }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Components.PixelButton {
                objectName: "intradayPreviewButton"
                text: root.i18n.catalog["quant.builder_preview"]
                enabled: !root.controller.busy && !operationRuntime.busy
                onClicked: { root.showPreview = true; root.controller.previewIntraday(root.values()) }
            }
            Components.PixelButton {
                objectName: "intradayBuildButton"
                text: root.i18n.catalog["quant.intraday_build"]
                variant: "primary"
                enabled: !root.controller.busy && !operationRuntime.busy
                onClicked: { root.pendingBuild = root.values(); saveDialog.open() }
            }
            Components.PixelButton {
                objectName: "intradayOpenButton"
                text: root.i18n.catalog["quant.intraday_open"]
                enabled: !root.controller.busy && !operationRuntime.busy
                onClicked: openDialog.open()
            }
            Components.PixelButton {
                text: root.i18n.catalog["quant.intraday_observations"]
                enabled: root.controller.intradayLoaded
                onClicked: root.showPreview = false
            }
            Components.PixelStatusBadge {
                status: root.controller.status
                text: root.i18n.statusLabel(root.controller.status)
            }
            Item { Layout.fillWidth: true }
        }
        Label {
            Layout.fillWidth: true
            text: root.i18n.catalog["quant.intraday_help"]
            color: Theme.PixelTheme.inkMuted
            wrapMode: Text.Wrap
            font.pixelSize: Theme.PixelTheme.fontSm
        }
        RowLayout {
            Layout.fillWidth: true
            Components.PixelTextField {
                id: dataPath
                objectName: "intradayDataPath"
                Layout.fillWidth: true
                text: root.controller.intradayPath
                placeholderText: root.i18n.catalog["quant.intraday_path"]
            }
            Components.PixelButton {
                objectName: "intradayInspectButton"
                text: root.i18n.catalog["quant.inspect"]
                enabled: !root.controller.busy && !operationRuntime.busy
                onClicked: { root.showPreview = false; root.controller.inspectIntraday(dataPath.text) }
            }
        }
        Components.SummaryStrip {
            Layout.fillWidth: true
            summary: root.showPreview ? root.controller.intradayPreviewSummary : root.controller.intradaySummary
            i18n: root.i18n
        }
        Components.DataTable {
            objectName: "intradayTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            tableModel: root.showPreview ? root.controller.intradayPreviewModel : root.controller.intradayModel
            i18n: root.i18n
            paged: !root.showPreview
            onPreviousRequested: root.controller.changeIntradayPage(-1)
            onNextRequested: root.controller.changeIntradayPage(1)
        }
    }
}
