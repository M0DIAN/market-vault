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
    property int workspaceIndex: 0

    function builderValues() {
        return {
            "symbol": builderSymbol.text,
            "start_date": builderStartDate.text,
            "end_date": builderEndDate.text,
            "interval": builderInterval.currentText,
            "preset": builderPreset.currentText,
            "horizon_trading_days": builderHorizon.text
        }
    }

    function featureResearchValues() {
        return {
            "label_field": featureLabel.currentText,
            "split": featureSplit.currentText,
            "quantile_count": featureQuantiles.text
        }
    }

    function backtestValues() {
        return {
            "signal_field": signalFeature.currentText,
            "comparator": comparator.currentText,
            "threshold": threshold.text,
            "return_label": returnLabel.currentText,
            "split": backtestSplit.currentText,
            "commission_bps": commission.text,
            "slippage_bps": slippage.text
        }
    }

    Connections {
        target: root.controller
        function onDatasetBuilt() { root.workspaceIndex = 1 }
    }

    FolderDialog {
        id: datasetFolderDialog
        objectName: "quantDatasetFolderDialog"
        title: root.i18n.catalog["quant.choose_dataset"]
        onAccepted: {
            datasetPath.text = selectedFolder.toString()
            root.controller.inspectDataset(datasetPath.text)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingMd

        Components.PixelPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: 126
            padding: Theme.PixelTheme.panelPadding
            ColumnLayout {
                anchors.fill: parent
                spacing: Theme.PixelTheme.spacingSm
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.PixelTheme.spacingSm
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Label {
                            text: root.i18n.catalog["quant.dataset_path"]
                            color: Theme.PixelTheme.inkMuted
                            font.pixelSize: Theme.PixelTheme.fontSm
                        }
                        Components.PixelTextField {
                            id: datasetPath
                            objectName: "quantDatasetPath"
                            Layout.fillWidth: true
                            placeholderText: root.i18n.catalog["quant.dataset_placeholder"]
                            text: root.controller.datasetPath
                        }
                    }
                    Components.PixelButton {
                        objectName: "quantBrowseButton"
                        text: root.i18n.catalog["quant.browse"]
                        glyph: "inventory"
                        enabled: !root.controller.busy && !operationRuntime.busy
                        onClicked: datasetFolderDialog.open()
                    }
                    Components.PixelButton {
                        objectName: "quantInspectButton"
                        text: root.i18n.catalog["quant.inspect"]
                        glyph: "inventory"
                        variant: "primary"
                        enabled: !root.controller.busy && !operationRuntime.busy
                        onClicked: root.controller.inspectDataset(datasetPath.text)
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: root.i18n.catalog["quant.dataset_help"]
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                    wrapMode: Text.Wrap
                }
                Components.SummaryStrip {
                    Layout.fillWidth: true
                    summary: root.controller.datasetSummary
                    i18n: root.i18n
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.PixelTheme.spacingSm
            Components.PixelButton {
                objectName: "quantBuilderTab"
                text: root.i18n.catalog["quant.builder_tab"]
                glyph: "inventory"
                variant: root.workspaceIndex === 0 ? "primary" : "secondary"
                onClicked: root.workspaceIndex = 0
            }
            Components.PixelButton {
                objectName: "quantFeatureTab"
                text: root.i18n.catalog["quant.feature_tab"]
                glyph: "pulse"
                variant: root.workspaceIndex === 1 ? "primary" : "secondary"
                onClicked: root.workspaceIndex = 1
            }
            Components.PixelButton {
                objectName: "quantBacktestTab"
                text: root.i18n.catalog["quant.backtest_tab"]
                glyph: "chart"
                variant: root.workspaceIndex === 2 ? "primary" : "secondary"
                onClicked: root.workspaceIndex = 2
            }
            Item { Layout.fillWidth: true }
            Label {
                visible: root.controller.error.length > 0
                text: root.controller.error
                color: Theme.PixelTheme.vermilionDark
                font.pixelSize: Theme.PixelTheme.fontSm
                elide: Text.ElideRight
                Layout.maximumWidth: 520
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.workspaceIndex

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    spacing: Theme.PixelTheme.spacingSm

                    Components.PixelPanel {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 194
                        padding: Theme.PixelTheme.panelPadding
                        GridLayout {
                            anchors.fill: parent
                            columns: 4
                            columnSpacing: Theme.PixelTheme.spacingMd
                            rowSpacing: 6

                            Components.LabeledTextField {
                                id: builderSymbol
                                objectName: "quantBuilderSymbol"
                                label: root.i18n.catalog["quant.builder_symbol"]
                                text: "US.SPY"
                            }
                            Components.PixelDateField {
                                id: builderStartDate
                                objectName: "quantBuilderStartDate"
                                label: root.i18n.catalog["field.start_date"]
                                language: root.i18n.language
                            }
                            Components.PixelDateField {
                                id: builderEndDate
                                objectName: "quantBuilderEndDate"
                                label: root.i18n.catalog["field.end_date"]
                                language: root.i18n.language
                            }
                            Components.LabeledComboBox {
                                id: builderInterval
                                objectName: "quantBuilderInterval"
                                label: root.i18n.catalog["field.interval"]
                                model: ["1m", "5m", "15m", "30m", "60m"]
                            }
                            Components.LabeledComboBox {
                                id: builderPreset
                                objectName: "quantBuilderPreset"
                                label: root.i18n.catalog["quant.builder_preset"]
                                model: ["CORE_TECHNICAL", "LIGHT_TECHNICAL"]
                            }
                            Components.LabeledTextField {
                                id: builderHorizon
                                objectName: "quantBuilderHorizon"
                                label: root.i18n.catalog["quant.builder_horizon"]
                                text: "1"
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: Theme.PixelTheme.formFieldMinimumWidth
                                Layout.maximumWidth: Theme.PixelTheme.formFieldWidth
                                spacing: 4
                                Label {
                                    text: root.i18n.catalog["quant.builder_cohort"]
                                    color: Theme.PixelTheme.inkMuted
                                    font.pixelSize: Theme.PixelTheme.fontSm
                                }
                                Components.PixelTag {
                                    text: "10.9-mv-ts2 / RTH / NONE"
                                }
                            }
                            Item {
                                Layout.preferredWidth: Theme.PixelTheme.formFieldWidth
                                Layout.preferredHeight: 1
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.PixelTheme.spacingSm
                        Components.PixelButton {
                            objectName: "quantBuilderPreviewButton"
                            text: root.i18n.catalog["quant.builder_preview"]
                            glyph: "audit"
                            variant: "primary"
                            enabled: !root.controller.busy
                                && !root.controller.confirmationPending
                                && !operationRuntime.busy
                            onClicked: root.controller.previewBuilder(root.builderValues())
                        }
                        Components.PixelButton {
                            objectName: "quantBuilderPrepareButton"
                            text: root.i18n.catalog["quant.builder_prepare"]
                            glyph: "network"
                            enabled: !root.controller.busy
                                && !root.controller.confirmationPending
                                && !operationRuntime.busy
                            onClicked: root.controller.requestPrepareResearchData(
                                root.builderValues()
                            )
                        }
                        Components.PixelButton {
                            objectName: "quantBuilderBuildButton"
                            text: root.i18n.catalog["quant.builder_build"]
                            glyph: "inventory"
                            variant: "primary"
                            enabled: root.controller.builderSummary["build_ready"] === "true"
                                && !root.controller.busy
                                && !root.controller.confirmationPending
                                && !operationRuntime.busy
                            onClicked: root.controller.buildDataset(root.builderValues())
                        }
                        Components.PixelStatusBadge {
                            status: root.controller.status
                            text: {
                                root.i18n.language
                                return root.i18n.statusLabel(root.controller.status)
                            }
                        }
                        Item { Layout.fillWidth: true }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.i18n.catalog["quant.builder_help"]
                        color: Theme.PixelTheme.inkMuted
                        font.pixelSize: Theme.PixelTheme.fontSm
                        wrapMode: Text.Wrap
                    }

                    Components.SummaryStrip {
                        Layout.fillWidth: true
                        summary: root.controller.builderSummary
                        i18n: root.i18n
                    }

                    Components.DataTable {
                        objectName: "quantBuilderTable"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.minimumHeight: 120
                        tableModel: root.controller.builderModel
                        i18n: root.i18n
                    }
                }
            }

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    spacing: Theme.PixelTheme.spacingSm
                    Components.PixelPanel {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 118
                        padding: Theme.PixelTheme.panelPadding
                        GridLayout {
                            anchors.fill: parent
                            columns: 4
                            columnSpacing: Theme.PixelTheme.spacingMd
                            rowSpacing: 6
                            Components.LabeledComboBox {
                                id: featureLabel
                                objectName: "quantFeatureLabel"
                                label: root.i18n.catalog["quant.label"]
                                model: root.controller.labelNames
                            }
                            Components.LabeledComboBox {
                                id: featureSplit
                                objectName: "quantFeatureSplit"
                                label: root.i18n.catalog["quant.split"]
                                model: ["TRAIN", "VALIDATION", "TEST"]
                            }
                            Components.LabeledTextField {
                                id: featureQuantiles
                                objectName: "quantFeatureQuantiles"
                                label: root.i18n.catalog["quant.quantiles"]
                                text: "5"
                            }
                            Components.PixelButton {
                                objectName: "quantRunFeatureButton"
                                Layout.alignment: Qt.AlignBottom
                                text: root.i18n.catalog["quant.run_feature"]
                                glyph: "pulse"
                                variant: "primary"
                                enabled: root.controller.datasetLoaded
                                    && root.controller.labelNames.length > 0
                                    && !root.controller.busy
                                    && !operationRuntime.busy
                                onClicked: root.controller.runFeatureResearch(root.featureResearchValues())
                            }
                        }
                    }
                    Components.SummaryStrip {
                        Layout.fillWidth: true
                        summary: root.controller.featureSummary
                        i18n: root.i18n
                    }
                    Label {
                        text: root.i18n.catalog["quant.feature_results"]
                        color: Theme.PixelTheme.ink
                        font.weight: Font.DemiBold
                        font.pixelSize: Theme.PixelTheme.fontMd
                    }
                    Components.DataTable {
                        objectName: "quantFeatureTable"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        tableModel: root.controller.featureModel
                        i18n: root.i18n
                    }
                }
            }

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    spacing: Theme.PixelTheme.spacingSm
                    Components.PixelPanel {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 188
                        padding: Theme.PixelTheme.panelPadding
                        GridLayout {
                            anchors.fill: parent
                            columns: 4
                            columnSpacing: Theme.PixelTheme.spacingMd
                            rowSpacing: 6
                            Components.LabeledComboBox {
                                id: signalFeature
                                objectName: "quantSignalFeature"
                                label: root.i18n.catalog["quant.signal_feature"]
                                model: root.controller.featureNames
                            }
                            Components.LabeledComboBox {
                                id: comparator
                                objectName: "quantComparator"
                                label: root.i18n.catalog["quant.comparator"]
                                model: ["GT", "GE", "LT", "LE"]
                            }
                            Components.LabeledTextField {
                                id: threshold
                                objectName: "quantThreshold"
                                label: root.i18n.catalog["quant.threshold"]
                                text: "0"
                            }
                            Components.LabeledComboBox {
                                id: returnLabel
                                objectName: "quantReturnLabel"
                                label: root.i18n.catalog["quant.return_label"]
                                model: root.controller.returnLabelNames
                            }
                            Components.LabeledComboBox {
                                id: backtestSplit
                                objectName: "quantBacktestSplit"
                                label: root.i18n.catalog["quant.split"]
                                model: ["TRAIN", "VALIDATION", "TEST"]
                                currentIndex: 2
                            }
                            Components.LabeledTextField {
                                id: commission
                                objectName: "quantCommission"
                                label: root.i18n.catalog["quant.commission_bps"]
                                text: "0"
                            }
                            Components.LabeledTextField {
                                id: slippage
                                objectName: "quantSlippage"
                                label: root.i18n.catalog["quant.slippage_bps"]
                                text: "0"
                            }
                            Components.PixelButton {
                                objectName: "quantRunBacktestButton"
                                Layout.alignment: Qt.AlignBottom
                                text: root.i18n.catalog["quant.run_backtest"]
                                glyph: "chart"
                                variant: "primary"
                                enabled: root.controller.datasetLoaded
                                    && root.controller.featureNames.length > 0
                                    && root.controller.returnLabelNames.length > 0
                                    && !root.controller.busy
                                    && !operationRuntime.busy
                                onClicked: root.controller.runBacktest(root.backtestValues())
                            }
                        }
                    }
                    Components.SummaryStrip {
                        Layout.fillWidth: true
                        summary: root.controller.backtestSummary
                        i18n: root.i18n
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: Theme.PixelTheme.spacingMd
                        Components.PixelPanel {
                            Layout.preferredWidth: 330
                            Layout.fillHeight: true
                            padding: Theme.PixelTheme.panelPadding
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: Theme.PixelTheme.spacingSm
                                Label {
                                    text: root.i18n.catalog["quant.equity_curve"]
                                    color: Theme.PixelTheme.ink
                                    font.weight: Font.DemiBold
                                    font.pixelSize: Theme.PixelTheme.fontMd
                                }
                                Item {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    Canvas {
                                        id: equityCanvas
                                        objectName: "quantEquityCanvas"
                                        anchors.fill: parent
                                        anchors.margins: 4
                                        onPaint: {
                                            const ctx = getContext("2d")
                                            ctx.clearRect(0, 0, width, height)
                                            const series = root.controller.equitySeries
                                            if (!series || series.length < 2 || width < 20 || height < 20)
                                                return
                                            let minValue = series[0]
                                            let maxValue = series[0]
                                            for (let i = 1; i < series.length; ++i) {
                                                minValue = Math.min(minValue, series[i])
                                                maxValue = Math.max(maxValue, series[i])
                                            }
                                            if (maxValue === minValue) {
                                                maxValue += 0.01
                                                minValue -= 0.01
                                            }
                                            const left = 8
                                            const top = 8
                                            const plotW = Math.max(1, width - 16)
                                            const plotH = Math.max(1, height - 16)
                                            ctx.strokeStyle = Theme.PixelTheme.line
                                            ctx.lineWidth = 1
                                            ctx.beginPath()
                                            ctx.moveTo(left, top)
                                            ctx.lineTo(left, top + plotH)
                                            ctx.lineTo(left + plotW, top + plotH)
                                            ctx.stroke()
                                            ctx.strokeStyle = Theme.PixelTheme.goldDark
                                            ctx.lineWidth = 2
                                            ctx.beginPath()
                                            for (let i = 0; i < series.length; ++i) {
                                                const x = left + plotW * i / Math.max(1, series.length - 1)
                                                const y = top + plotH * (maxValue - series[i]) / (maxValue - minValue)
                                                if (i === 0) ctx.moveTo(x, y)
                                                else ctx.lineTo(x, y)
                                            }
                                            ctx.stroke()
                                        }
                                    }
                                    Connections {
                                        target: root.controller
                                        function onResearchChanged() { equityCanvas.requestPaint() }
                                    }
                                    Components.PixelEmptyState {
                                        anchors.centerIn: parent
                                        visible: root.controller.equitySeries.length < 2
                                        text: root.i18n.catalog["quant.no_backtest"]
                                    }
                                }
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            spacing: Theme.PixelTheme.spacingSm
                            Label {
                                text: root.i18n.catalog["quant.trades"]
                                color: Theme.PixelTheme.ink
                                font.weight: Font.DemiBold
                                font.pixelSize: Theme.PixelTheme.fontMd
                            }
                            Components.DataTable {
                                objectName: "quantTradesTable"
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                paged: true
                                tableModel: root.controller.tradesModel
                                i18n: root.i18n
                                onPreviousRequested: root.controller.previousTradesPage()
                                onNextRequested: root.controller.nextTradesPage()
                            }
                        }
                    }
                }
            }
        }
    }

    Components.OpenDConfirmDialog {
        controller: root.controller
        i18n: root.i18n
    }
}
