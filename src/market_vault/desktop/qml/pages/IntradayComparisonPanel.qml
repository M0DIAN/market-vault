import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

ColumnLayout {
    id: root
    objectName: "intradayComparisonPanel"
    required property var controller
    required property var i18n
    property string sourceKey: ""
    property int restoreRevision: -1
    spacing: Theme.PixelTheme.spacingSm

    function sync() {
        if (root.controller.sourceId && root.controller.sourceId !== root.sourceKey) {
            root.sourceKey = root.controller.sourceId
            settings.applySource(root.sourceKey, root.controller.featureNames, root.controller.defaults)
        }
        if (root.restoreRevision !== root.controller.restoreRevision) {
            root.restoreRevision = root.controller.restoreRevision
            const plan = root.controller.restoredPlan
            if (plan.strategies) {
                settings.featureOptions = root.controller.sourceId === plan.data_id ? root.controller.featureNames : plan.feature_fields.slice()
                settings.applyPlan(plan, true)
            }
        }
        candidate.currentIndex = root.controller.candidateIndex
        equity.requestPaint()
    }
    Component.onCompleted: sync()
    Connections { target: root.controller; function onChanged() { root.sync() } }

    IntradayResearchSettings { id: settings; i18n: root.i18n }
    StrategyDiagnosticsDialog {
        id: diagnostics
        objectName: "intradayDiagnosticsDialog"
        controller: root.controller
        i18n: root.i18n
        inputAvailable: root.controller.dataLoaded
        submit: function(values) { return root.controller.runDiagnostics(values) }
    }
    FileDialog {
        id: openDialog
        objectName: "intradayExperimentOpenDialog"
        title: root.i18n.catalog["quant.open_experiment"]
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.openExperiment(selectedFile.toString())
    }
    FileDialog {
        id: saveDialog
        objectName: "intradayExperimentSaveDialog"
        title: root.i18n.catalog["quant.save_experiment"]
        fileMode: FileDialog.SaveFile
        nameFilters: ["JSON files (*.json)"]
        defaultSuffix: "json"
        onAccepted: root.controller.saveExperiment(selectedFile.toString())
    }
    FileDialog {
        id: relocateDialog
        objectName: "intradayExperimentRelocateDialog"
        title: root.i18n.catalog["quant.replay_relocated"]
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.replayExperiment(selectedFile.toString())
    }
    RowLayout {
        Layout.fillWidth: true
        enabled: !root.controller.busy && !operationRuntime.busy
        Components.PixelButton { objectName: "intradayResearchSettingsButton"; text: root.i18n.catalog["quant.intraday_settings"]; onClicked: settings.open() }
        Components.PixelButton {
            objectName: "intradayRunComparisonButton"
            text: root.i18n.catalog["quant.run_comparison"]
            variant: "primary"
            enabled: root.controller.dataLoaded
            onClicked: root.controller.runComparison(settings.values())
        }
        Components.PixelButton {
            objectName: "intradayOpenDiagnosticsButton"
            text: root.i18n.catalog["quant.diagnose_strategy"]
            enabled: root.controller.dataLoaded
            onClicked: diagnostics.prepare(settings.values(), root.controller.diagnosticPlan, root.controller.restoreRevision)
        }
        Item { Layout.fillWidth: true }
        Components.PixelStatusBadge { status: root.controller.status; text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) } }
    }
    Label {
        objectName: "intradayResearchBoundaries"
        Layout.fillWidth: true
        text: settings.summary
        wrapMode: Text.WordWrap
        color: Theme.PixelTheme.inkMuted
        font.pixelSize: Theme.PixelTheme.fontSm
    }
    RowLayout {
        Layout.fillWidth: true
        enabled: !root.controller.busy && !operationRuntime.busy
        Components.PixelButton { objectName: "intradayExperimentOpenButton"; text: root.i18n.catalog["quant.open_experiment"]; onClicked: openDialog.open() }
        Components.PixelButton { objectName: "intradayExperimentSaveButton"; text: root.i18n.catalog["quant.save_experiment"]; enabled: root.controller.resultLoaded; onClicked: saveDialog.open() }
        Components.PixelButton { objectName: "intradayExperimentReplayButton"; text: root.i18n.catalog["quant.replay_experiment"]; enabled: root.controller.resultLoaded; onClicked: root.controller.replayExperiment("") }
        Components.PixelButton { objectName: "intradayExperimentRelocateButton"; text: root.i18n.catalog["quant.replay_relocated"]; enabled: root.controller.resultLoaded; onClicked: relocateDialog.open() }
    }
    Label {
        Layout.fillWidth: true
        visible: text.length > 0
        text: root.controller.error || root.controller.sourceNote
        wrapMode: Text.WordWrap
        color: Theme.PixelTheme.ink
        font.pixelSize: Theme.PixelTheme.fontSm
    }
    Components.SummaryStrip {
        Layout.fillWidth: true
        i18n: root.i18n
        summary: {
            const result = root.controller.resultSummary
            const keys = {COMPUTED: "quant.intraday_computed", RECORDED: "quant.snapshot_loaded",
                REPLAY_MATCH: "quant.replay_verified", REPLAY_PENDING: "quant.intraday_replay_pending",
                REPLAY_FAILED: "quant.intraday_replay_failed"}
            if (result.intraday_verification) result.intraday_verification = root.i18n.catalog[keys[result.intraday_verification]]
            return result
        }
    }
    Label {
        objectName: "intradayResearchResultDetails"
        Layout.fillWidth: true
        visible: root.controller.resultLoaded
        text: root.controller.resultDetails
        elide: Text.ElideMiddle
        color: Theme.PixelTheme.inkMuted
        font.pixelSize: Theme.PixelTheme.fontSm
        ToolTip.visible: detailsHover.hovered
        ToolTip.text: root.controller.resultDetails + "\n" + root.controller.experimentPath
        HoverHandler { id: detailsHover }
    }
    RowLayout {
        Layout.fillWidth: true
        Components.LabeledComboBox {
            id: candidate
            objectName: "intradayResearchCandidate"
            Layout.fillWidth: true
            label: root.i18n.catalog["columns.strategy"]
            model: root.controller.candidateNames
            onSelected: root.controller.selectCandidate(currentIndex)
        }
        Components.LabeledComboBox {
            id: view
            objectName: "intradayResearchView"
            Layout.preferredWidth: 250
            label: root.i18n.catalog["quant.intraday_result_view"]
            property int selectedView: 0
            model: ["quant.intraday_overview", "quant.trades", "quant.intraday_ledger", "quant.intraday_daily",
                "quant.intraday_models", "quant.intraday_predictions", "quant.intraday_contributions"].map(key => root.i18n.catalog[key])
            onSelected: { selectedView = currentIndex; root.controller.selectView(currentIndex) }
            onModelChanged: currentIndex = selectedView
        }
    }
    ColumnLayout {
        visible: root.controller.resultLoaded
        Layout.fillWidth: true
        spacing: 2
        Label { text: root.i18n.catalog["quant.intraday_equity_legend"]; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm }
        Canvas {
            id: equity
            objectName: "intradayResearchEquity"
            Layout.fillWidth: true
            Layout.preferredHeight: 86
            onWidthChanged: requestPaint()
            onPaint: {
                const ctx = getContext("2d"), series = root.controller.equitySeries
                ctx.clearRect(0, 0, width, height)
                if (!series.length) return
                const points = series[0].concat(series[1])
                let xmin = points[0][0], xmax = xmin, ymin = 1, ymax = 1
                points.forEach(p => { xmin = Math.min(xmin, p[0]); xmax = Math.max(xmax, p[0]); ymin = Math.min(ymin, p[1]); ymax = Math.max(ymax, p[1]) })
                const dy = ymax - ymin || 0.01, dx = xmax - xmin || 1
                const y = value => height - 12 - (value - ymin) / dy * (height - 24)
                ctx.strokeStyle = "#7a756a"; ctx.lineWidth = 1
                ctx.beginPath(); ctx.moveTo(42, y(1)); ctx.lineTo(width - 8, y(1)); ctx.stroke()
                ctx.fillStyle = "#7a756a"; ctx.font = "10px sans-serif"
                ctx.fillText(ymax.toFixed(3), 0, 12); ctx.fillText(ymin.toFixed(3), 0, height - 3)
                series.forEach((values, index) => {
                    ctx.strokeStyle = index === 0 ? "#9a7427" : "#4a8294"; ctx.lineWidth = 2
                    ctx.beginPath()
                    values.forEach((p, i) => { const x = 42 + (p[0] - xmin) / dx * (width - 50); if (i) ctx.lineTo(x, y(p[1])); else ctx.moveTo(x, y(p[1])) })
                    ctx.stroke()
                })
            }
        }
    }
    Components.DataTable {
        objectName: "intradayResearchTable"
        Layout.fillWidth: true
        Layout.fillHeight: true
        paged: true
        tableModel: root.controller.tableModel
        i18n: root.i18n
        onPreviousRequested: root.controller.changePage(-1)
        onNextRequested: root.controller.changePage(1)
    }
}
