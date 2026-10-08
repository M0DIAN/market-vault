import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

ColumnLayout {
    id: root
    objectName: "quantStrategyComparisonPanel"
    required property var controller
    required property var i18n
    property string datasetKey: ""
    property var featureOptions: []
    property var returnOptions: []
    property string equityKey: ""
    property string comparisonKey: ""
    property var equityOptions: []
    property int resultsView: 0
    property bool showInputs: true
    spacing: Theme.PixelTheme.spacingSm

    function syncDataset() {
        const key = root.controller.datasetPath + "|" + (root.controller.datasetSummary.dataset_id || "")
        if (!root.controller.datasetLoaded || key === root.datasetKey)
            return
        root.datasetKey = key
        root.showInputs = true
        root.featureOptions = root.controller.featureNames
        root.returnOptions = root.controller.returnLabelNames
        const index = Math.max(0, root.featureOptions.indexOf("return_2"))
        commonFeatures.text = root.featureOptions[index] || ""
        strategyEditor.reset(root.featureOptions[index] || "")
        returnLabel.currentIndex = 0
    }

    function syncEquity() {
        const comparisonId = root.controller.comparisonSummary.comparison_id || ""
        if (!comparisonId)
            root.showInputs = true
        else if (comparisonId !== root.comparisonKey)
            root.showInputs = false
        root.comparisonKey = comparisonId
        const equityId = root.controller.comparisonSummary.equity_comparison_id || ""
        const riskId = root.controller.comparisonSummary.risk_report_id || ""
        const key = equityId ? equityId + "|" + riskId : ""
        if (!riskId && root.resultsView === 2) root.resultsView = 0
        if (key !== root.equityKey) {
            root.equityKey = key
            root.equityOptions = root.controller.comparisonEquityNames
            if (!key) root.resultsView = 0
        }
        equityStrategy.currentIndex = root.controller.comparisonEquityIndex
        equityCanvas.requestPaint()
    }

    Component.onCompleted: { syncDataset(); syncEquity() }
    Connections {
        target: root.controller
        function onResearchChanged() { root.syncDataset(); root.syncEquity() }
    }

    function comparisonValues() {
        return {
            "feature_fields": commonFeatures.text.split(",").map(value => value.trim()),
            "strategies": strategyEditor.snapshot(),
            "return_label": returnLabel.currentText,
            "minimum_train_periods": trainPeriods.text,
            "validation_periods": validationPeriods.text,
            "step_periods": stepPeriods.text,
            "commission_bps": commission.text,
            "slippage_bps": slippage.text,
            "equity_curve": equityToggle.checked,
            "risk_report": riskToggle.checked
        }
    }

    Components.PixelPanel {
        visible: root.showInputs
        Layout.fillWidth: true
        Layout.preferredHeight: 258
        padding: Theme.PixelTheme.panelPadding
        RowLayout {
            anchors.fill: parent
            spacing: Theme.PixelTheme.spacingMd
            GridLayout {
                Layout.preferredWidth: 310
                Layout.maximumWidth: 310
                Layout.fillHeight: true
                columns: 2
                columnSpacing: 8
                rowSpacing: 6
                Components.LabeledTextField {
                    id: commonFeatures
                    objectName: "quantComparisonFeatures"
                    Layout.minimumWidth: 120
                    label: root.i18n.catalog["quant.common_features"]
                    text: "return_2"
                }
                Components.LabeledComboBox {
                    id: returnLabel
                    objectName: "quantComparisonReturnLabel"
                    Layout.minimumWidth: 120
                    label: root.i18n.catalog["quant.return_label"]
                    model: root.returnOptions
                }
                Components.LabeledTextField {
                    id: trainPeriods
                    objectName: "quantComparisonTrainPeriods"
                    Layout.minimumWidth: 120
                    label: root.i18n.catalog["quant.train_periods"]
                    text: "20"
                }
                Components.LabeledTextField {
                    id: validationPeriods
                    objectName: "quantComparisonValidationPeriods"
                    Layout.minimumWidth: 120
                    label: root.i18n.catalog["quant.validation_periods"]
                    text: "5"
                }
                Components.LabeledTextField {
                    id: stepPeriods
                    objectName: "quantComparisonStepPeriods"
                    Layout.minimumWidth: 120
                    label: root.i18n.catalog["quant.step_periods"]
                    text: "5"
                }
                Components.LabeledTextField {
                    id: commission
                    Layout.minimumWidth: 120
                    label: root.i18n.catalog["quant.commission_bps"]
                    text: "0"
                }
                Components.LabeledTextField {
                    id: slippage
                    Layout.minimumWidth: 120
                    label: root.i18n.catalog["quant.slippage_bps"]
                    text: "0"
                }
            }
            StrategyListEditor {
                id: strategyEditor
                Layout.fillWidth: true
                Layout.fillHeight: true
                i18n: root.i18n
                featureOptions: root.featureOptions
                defaultFeature: commonFeatures.text.split(",")[0].trim()
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Components.PixelButton {
            objectName: "quantRunComparisonButton"
            text: root.i18n.catalog["quant.run_comparison"]
            glyph: "chart"
            variant: "primary"
            enabled: root.controller.datasetLoaded
                && root.controller.featureNames.length > 0
                && root.controller.returnLabelNames.length > 0
                && !root.controller.busy && !operationRuntime.busy
            onClicked: root.controller.runStrategyComparison(root.comparisonValues())
        }
        CheckBox {
            id: equityToggle
            objectName: "quantComparisonEquityToggle"
            text: root.i18n.catalog["quant.include_equity"]
            checked: false
            enabled: !riskToggle.checked
        }
        CheckBox {
            id: riskToggle
            objectName: "quantComparisonRiskToggle"
            text: root.i18n.catalog["quant.include_risk"]
            checked: false
            onCheckedChanged: { if (checked) equityToggle.checked = true }
        }
        Components.PixelButton {
            objectName: "quantComparisonInputsButton"
            visible: !!root.controller.comparisonSummary.comparison_id
            text: root.i18n.catalog[root.showInputs ? "quant.collapse_inputs" : "quant.expand_inputs"]
            onClicked: root.showInputs = !root.showInputs
        }
        Label {
            Layout.fillWidth: true
            text: root.i18n.catalog["quant.comparison_help"]
            wrapMode: Text.WordWrap
            color: Theme.PixelTheme.inkMuted
            font.pixelSize: Theme.PixelTheme.fontSm
        }
    }
    Components.SummaryStrip {
        Layout.fillWidth: true
        summary: root.controller.comparisonSummary
        i18n: root.i18n
    }
    RowLayout {
        visible: root.equityOptions.length > 0
        Layout.fillWidth: true
        Components.PixelButton {
            objectName: "quantComparisonResultsButton"
            text: root.i18n.catalog["quant.comparison_results"]
            variant: root.resultsView === 0 ? "primary" : "secondary"
            onClicked: root.resultsView = 0
        }
        Components.PixelButton {
            objectName: "quantComparisonLedgerButton"
            text: root.i18n.catalog["quant.equity_ledger"]
            variant: root.resultsView === 1 ? "primary" : "secondary"
            onClicked: { root.resultsView = 1; root.showInputs = false }
        }
        Components.PixelButton {
            objectName: "quantComparisonRiskButton"
            visible: !!root.controller.comparisonSummary.risk_report_id
            text: root.i18n.catalog["quant.risk_results"]
            variant: root.resultsView === 2 ? "primary" : "secondary"
            onClicked: { root.resultsView = 2; root.showInputs = false }
        }
        Item { Layout.fillWidth: true }
        Components.PixelComboBox {
            id: equityStrategy
            objectName: "quantComparisonEquityStrategy"
            visible: root.resultsView === 1
            Layout.preferredWidth: 180
            model: root.equityOptions
            onActivated: index => root.controller.selectComparisonEquity(index)
        }
    }
    Label {
        visible: root.resultsView === 2
        Layout.fillWidth: true
        text: root.i18n.catalog["quant.risk_help"]
        wrapMode: Text.WordWrap
        color: Theme.PixelTheme.inkMuted
        font.pixelSize: Theme.PixelTheme.fontSm
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Components.PixelPanel {
            visible: root.resultsView === 1
            Layout.preferredWidth: 310
            Layout.fillHeight: true
            padding: Theme.PixelTheme.panelPadding
            ColumnLayout {
                anchors.fill: parent
                Label {
                    text: root.i18n.catalog["quant.bar_equity"]
                    color: Theme.PixelTheme.ink
                    font.weight: Font.DemiBold
                }
                Label {
                    Layout.fillWidth: true
                    text: root.i18n.catalog["quant.equity_help"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    visible: root.controller.comparisonBenchmarkSeries.length > 0
                    Layout.fillWidth: true
                    text: root.i18n.catalog["quant.benchmark_legend"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Canvas {
                    id: equityCanvas
                    objectName: "quantComparisonEquityCanvas"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    onVisibleChanged: requestPaint()
                    onPaint: {
                        const ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        const series = root.controller.comparisonEquitySeries
                        if (!series || series.length < 2 || width < 60 || height < 40) return
                        const benchmark = root.controller.comparisonBenchmarkSeries
                        const all = series.concat(benchmark)
                        let lo = series[0][1], hi = lo
                        for (let i = 1; i < all.length; ++i) {
                            lo = Math.min(lo, all[i][1]); hi = Math.max(hi, all[i][1])
                        }
                        if (lo === hi) { lo -= 0.01; hi += 0.01 }
                        const left = 48, top = 12, w = width - 56, h = height - 24
                        const start = series[0][0], duration = Math.max(1, series[series.length - 1][0] - start)
                        ctx.strokeStyle = Theme.PixelTheme.line
                        ctx.lineWidth = 1
                        ctx.beginPath(); ctx.moveTo(left, top); ctx.lineTo(left, top + h); ctx.lineTo(left + w, top + h); ctx.stroke()
                        ctx.fillStyle = Theme.PixelTheme.inkMuted
                        ctx.font = "10px sans-serif"
                        ctx.fillText(hi.toFixed(3), 0, top + 4)
                        ctx.fillText(lo.toFixed(3), 0, top + h)
                        const draw = function(points, color) {
                            if (!points || points.length < 2) return
                            ctx.strokeStyle = color
                            ctx.lineWidth = 2
                            ctx.beginPath()
                            let previousY = top + h * (hi - points[0][1]) / (hi - lo)
                            for (let i = 0; i < points.length; ++i) {
                                const x = left + w * (points[i][0] - start) / duration
                                const y = top + h * (hi - points[i][1]) / (hi - lo)
                                if (i === 0) ctx.moveTo(x, y)
                                else { ctx.lineTo(x, previousY); ctx.lineTo(x, y) }
                                previousY = y
                            }
                            ctx.stroke()
                        }
                        draw(benchmark, Theme.PixelTheme.inkMuted)
                        draw(series, Theme.PixelTheme.goldDark)
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: {
                        const series = root.controller.comparisonEquitySeries
                        if (!series || series.length < 2) return ""
                        return new Date(series[0][0]).toISOString().slice(0, 16) + " → "
                            + new Date(series[series.length - 1][0]).toISOString().slice(0, 16) + " UTC"
                    }
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
        }
        Components.DataTable {
            objectName: "quantComparisonTable"
            visible: root.resultsView === 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            tableModel: root.controller.comparisonModel
            i18n: root.i18n
        }
        Components.DataTable {
            objectName: "quantComparisonRiskTable"
            visible: root.resultsView === 2
            Layout.fillWidth: true
            Layout.fillHeight: true
            tableModel: root.controller.comparisonRiskModel
            i18n: root.i18n
        }
        Components.DataTable {
            objectName: "quantComparisonEquityTable"
            visible: root.resultsView === 1
            Layout.fillWidth: true
            Layout.fillHeight: true
            paged: true
            tableModel: root.controller.comparisonEquityModel
            i18n: root.i18n
            onPreviousRequested: root.controller.changeComparisonEquityPage(-1)
            onNextRequested: root.controller.changeComparisonEquityPage(1)
        }
    }
}
