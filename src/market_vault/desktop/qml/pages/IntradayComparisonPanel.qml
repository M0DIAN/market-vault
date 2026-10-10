import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradayComparisonPanel"
    required property var controller
    required property var i18n
    property string sourceKey: ""
    property int restoreRevision: -1
    property int draftRevision: -1
    readonly property string editorRevision: root.controller.draftLoaded
        ? "draft:" + root.controller.draftRevision : "result:" + root.controller.restoreRevision
    readonly property var gridData: root.controller.parameterGrid
    readonly property var uncertaintyData: root.controller.uncertaintySummary
    readonly property var familyData: root.controller.familyBoundsSummary
    readonly property var sequentialData: root.controller.sequentialSummary
    property bool showSequentialDetails: false
    readonly property var sequentialFold: (root.sequentialData.folds || [])[sequentialFoldPicker.currentIndex] || ({})
    readonly property var signalDelayData: root.controller.signalDelaySummary
    readonly property var signalDelayDetail: root.controller.signalDelayDetails
    property bool showSignalDelayDetails: false
    readonly property var predictionData: root.controller.predictionQualitySummary
    readonly property var predictionFold: root.controller.predictionQualityFold
    property bool showPredictionDetails: false
    readonly property var gridMetrics: ["total_return", "observed_max_drawdown", "trade_count",
        "worst_fold_return", "median_fold_return", "best_fold_return"]

    function gridLabel(key) {
        return root.i18n.catalog["grid." + key] || root.i18n.catalog["risk." + key]
            || root.i18n.catalog["comparison." + key] || root.i18n.catalog["performance." + key]
            || root.i18n.catalog["columns." + key] || key
    }
    function uncertaintyLabel(key) {
        return root.i18n.catalog["uncertainty." + key] || root.i18n.catalog["risk." + key]
            || root.i18n.catalog["comparison." + key] || root.i18n.catalog["performance." + key] || key
    }
    function familyLabel(key) {
        return root.i18n.catalog["family_bounds." + key] || root.uncertaintyLabel(key)
    }
    function sequentialLabel(key) {
        return root.i18n.catalog["sequential." + key] || root.i18n.catalog["columns." + key] || root.familyLabel(key)
    }
    function signalDelayLabel(key) {
        return root.i18n.catalog["signal_delay." + key] || root.i18n.catalog["columns." + key] || root.uncertaintyLabel(key)
    }
    function predictionLabel(key) {
        return root.i18n.catalog["prediction_quality." + key] || root.i18n.catalog["columns." + key] || key
    }
    function signalDelayStatus(check) {
        return root.signalDelayLabel(check.status)
            + (check.unavailable_reason ? " · " + root.signalDelayLabel(check.unavailable_reason) : "")
            + (check.detail ? "\n" + check.detail : "")
    }
    function axisName(axis) {
        return root.i18n.catalog["grid.axis"] + " " + axis.axis_index + " · "
            + root.gridLabel("strategy." + axis.parameter)
            + (axis.condition_index !== undefined ? " · " + root.i18n.catalog["grid.condition"] + " " + axis.condition_index : "")
    }
    function coordinates(row, stacked) {
        return (root.gridData.axes || []).map((axis, i) => root.axisName(axis) + (stacked ? "\n" : " = ") + row.axis_values[i]).join("\n")
            || root.i18n.catalog["grid.no_axes"]
    }
    function gridAmount(metric) {
        return metric.display + (metric.unit === "RATIO" ? "" : " " + root.gridLabel(metric.unit))
    }

    function sync() {
        settings.availableFeatures = root.controller.featureNames
        settings.availableDataId = root.controller.sourceId
        if (root.controller.sourceId && root.controller.sourceId !== root.sourceKey) {
            root.sourceKey = root.controller.sourceId
            if (!root.controller.draftLoaded)
                settings.applySource(root.sourceKey, root.controller.featureNames, root.controller.defaults, root.controller.dataPath)
        }
        if (root.controller.draftLoaded && root.draftRevision !== root.controller.draftRevision) {
            root.draftRevision = root.controller.draftRevision
            const draft = root.controller.draftPlan
            settings.applyPlan(draft.comparison_plan || draft, true)
        } else if (!root.controller.draftLoaded && root.restoreRevision !== root.controller.restoreRevision) {
            const plan = root.controller.restoredPlan
            if (plan.strategies) settings.applyPlan(plan, true)
        }
        root.restoreRevision = root.controller.restoreRevision
        scenario.currentIndex = root.controller.scenarioIndex
        candidate.currentIndex = root.controller.candidateIndex
        view.currentIndex = root.controller.viewIndex
        gridCost.currentIndex = root.controller.gridCostIndex
        gridMetric.currentIndex = root.controller.gridMetricIndex
        if (predictionSource.text !== root.controller.predictionQualitySource)
            predictionSource.text = root.controller.predictionQualitySource
        equity.requestPaint()
    }
    Component.onCompleted: sync()
    Connections { target: root.controller; function onChanged() { root.sync() } }

    function prepareDiagnostics() {
        root.controller.cancelPlanSave()
        diagnostics.prepare(settings.values(), root.controller.draftLoaded ? root.controller.draftPlan : root.controller.diagnosticPlan,
            root.editorRevision)
    }
    function prepareScenarios() {
        root.controller.cancelPlanSave()
        scenarios.prepare(settings.values(), root.controller.draftLoaded ? root.controller.draftPlan : root.controller.scenarioPlan,
            root.editorRevision)
    }
    function preparePlanSave(kind, values) {
        if (root.controller.preparePlanSave(kind, values)) planSaveDialog.open()
    }
    function editDraft() {
        const draft = root.controller.draftPlan
        if (draft.parameter_axes !== undefined) root.prepareDiagnostics()
        else if (draft.execution_scenarios !== undefined) root.prepareScenarios()
        else { root.controller.cancelPlanSave(); settings.open() }
    }
    function planKind(plan) {
        return plan.parameter_axes !== undefined ? "diagnostics" : (plan.execution_scenarios !== undefined ? "scenarios" : "comparison")
    }

    IntradayResearchSettings {
        id: settings
        i18n: root.i18n
        errorText: root.controller.error
        savePlan: function(values) { root.preparePlanSave("comparison", values) }
    }
    IntradayExecutionScenariosDialog {
        id: scenarios
        controller: root.controller
        i18n: root.i18n
        savePlan: function(values) { root.preparePlanSave("scenarios", values) }
    }
    StrategyDiagnosticsDialog {
        id: diagnostics
        objectName: "intradayDiagnosticsDialog"
        controller: root.controller
        i18n: root.i18n
        inputAvailable: root.controller.dataLoaded
        submit: function(values) { return root.controller.runDiagnostics(values) }
        savePlan: function(values) { root.preparePlanSave("diagnostics", values) }
        preserveCosts: true
    }
    FileDialog {
        id: planOpenDialog
        objectName: "intradayPlanOpenDialog"
        title: root.i18n.catalog["plan.load"]
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.loadPlan(selectedFile.toString())
    }
    FileDialog {
        id: planSaveDialog
        objectName: "intradayPlanSaveDialog"
        title: root.i18n.catalog["plan.save_" + root.controller.pendingPlanKind] || root.i18n.catalog["plan.save"]
        fileMode: FileDialog.SaveFile
        options: FileDialog.DontConfirmOverwrite
        nameFilters: ["JSON files (*.json)"]
        defaultSuffix: "json"
        onAccepted: root.controller.savePreparedPlan(selectedFile.toString())
        onRejected: root.controller.cancelPlanSave()
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
        title: root.i18n.catalog[root.controller.scenariosLoaded ? "quant.scenarios_save" : "quant.save_experiment"]
        fileMode: FileDialog.SaveFile
        nameFilters: ["JSON files (*.json)"]
        defaultSuffix: "json"
        onAccepted: root.controller.saveExperiment(selectedFile.toString())
    }
    FileDialog {
        id: exportDialog
        objectName: "intradayScenarioExportDialog"
        title: root.i18n.catalog["quant.scenario_export"]
        fileMode: FileDialog.SaveFile
        nameFilters: ["JSON files (*.json)"]
        defaultSuffix: "json"
        onAccepted: root.controller.exportScenario(selectedFile.toString())
    }
    FileDialog {
        id: relocateDialog
        objectName: "intradayExperimentRelocateDialog"
        title: root.i18n.catalog["quant.replay_relocated"]
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.replayExperiment(selectedFile.toString())
    }
    FileDialog {
        id: predictionSourceDialog
        objectName: "intradayPredictionSourceDialog"
        title: root.i18n.catalog["prediction_quality.locate"]
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.setPredictionQualitySource(selectedFile.toString())
    }
    ScrollView {
        id: scroll
        objectName: "intradayResearchScroll"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar { objectName: "intradayResearchScrollBar" }

        ColumnLayout {
            width: scroll.availableWidth
            height: Math.max(implicitHeight, scroll.availableHeight)
            spacing: Theme.PixelTheme.spacingSm
            RowLayout {
                Layout.fillWidth: true
                enabled: !root.controller.busy && !operationRuntime.busy
                Components.PixelButton { objectName: "intradayResearchSettingsButton"; text: root.i18n.catalog["quant.intraday_settings"]; onClicked: { root.controller.cancelPlanSave(); settings.open() } }
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
                    enabled: settings.dataId.length > 0
                    onClicked: root.prepareDiagnostics()
                }
                Components.PixelButton {
                    objectName: "intradayOpenScenariosButton"
                    text: root.i18n.catalog["quant.execution_scenarios"]
                    enabled: settings.dataId.length > 0
                    onClicked: root.prepareScenarios()
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
                Components.PixelButton { objectName: "intradayExperimentSaveButton"; text: root.i18n.catalog[root.controller.scenariosLoaded ? "quant.scenarios_save" : "quant.save_experiment"]; enabled: root.controller.resultLoaded; onClicked: saveDialog.open() }
                Components.PixelButton { objectName: "intradayExperimentReplayButton"; text: root.i18n.catalog[root.controller.scenariosLoaded ? "quant.scenarios_replay" : "quant.replay_experiment"]; enabled: root.controller.resultLoaded; onClicked: root.controller.replayExperiment("") }
                Components.PixelButton { objectName: "intradayExperimentRelocateButton"; text: root.i18n.catalog["quant.replay_relocated"]; enabled: root.controller.resultLoaded; onClicked: relocateDialog.open() }
            }
            Label {
                objectName: "intradayPlanDraftNotice"
                Layout.fillWidth: true
                visible: root.controller.draftLoaded
                text: {
                    const draft = root.controller.draftPlan, source = root.controller.draftSource
                    if (!root.controller.draftLoaded) return ""
                    return root.i18n.catalog["plan.bound_draft"] + " · " + root.i18n.catalog["plan.kind_" + root.planKind(draft)]
                        + "\n" + root.i18n.catalog["plan.source_" + source.kind] + ": " + source.path
                        + (source.kind === "CANDIDATE" ? "\n" + root.i18n.catalog["grid.cost_index"] + " " + source.cost_index
                            + " · " + root.i18n.catalog["grid.candidate"] + " " + source.candidate_index + " · " + source.candidate_id : "")
                        + "\n" + root.i18n.catalog["plan.separate_results"]
                }
                wrapMode: Text.WrapAnywhere
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                enabled: !root.controller.busy && !operationRuntime.busy
                Components.PixelButton { objectName: "intradayPlanLoadButton"; text: root.i18n.catalog["plan.load"]; onClicked: planOpenDialog.open() }
                Components.PixelButton {
                    objectName: "intradayPlanContinueButton"
                    text: root.i18n.catalog["plan.continue"]
                    enabled: root.controller.canContinueCandidate
                    onClicked: root.controller.continueCandidate()
                }
                Components.PixelButton { objectName: "intradayPlanEditButton"; text: root.i18n.catalog["plan.edit"]; enabled: root.controller.draftLoaded; onClicked: root.editDraft() }
                Item { Layout.fillWidth: true }
            }
            Label {
                objectName: "intradayPlanSaveReceipt"
                Layout.fillWidth: true
                visible: !!root.controller.planSaveReceipt.path
                text: {
                    const saved = root.controller.planSaveReceipt
                    return saved.path ? root.i18n.catalog["plan.saved_capture"] + " · " + root.i18n.catalog["plan.kind_" + saved.kind]
                        + ": " + saved.path + "\nSHA-256: " + saved.content_sha256 : ""
                }
                wrapMode: Text.WrapAnywhere
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
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
                ToolTip.text: root.controller.resultDetails + "\n" + (root.controller.scenariosLoaded ? root.controller.collectionPath : root.controller.experimentPath)
                HoverHandler { id: detailsHover }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: root.controller.scenariosLoaded
                enabled: !root.controller.busy && !operationRuntime.busy
                Components.LabeledComboBox {
                    id: scenario
                    objectName: "intradayResearchScenario"
                    Layout.fillWidth: true
                    Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.execution_scenario"]
                    model: root.controller.scenarioNames
                    onSelected: root.controller.selectScenario(currentIndex)
                }
                Components.PixelButton {
                    objectName: "intradayScenarioExportButton"
                    text: root.i18n.catalog["quant.scenario_export"]
                    onClicked: exportDialog.open()
                }
            }
            Label {
                objectName: "intradayScenarioExportStatus"
                Layout.fillWidth: true
                visible: root.controller.scenariosLoaded
                text: root.i18n.catalog[root.controller.experimentPath ? "quant.scenario_exported" : "quant.scenario_export_required"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
                ToolTip.visible: exportHover.hovered
                ToolTip.text: root.controller.experimentPath
                HoverHandler { id: exportHover }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledComboBox {
                    id: candidate
                    objectName: "intradayResearchCandidate"
                    Layout.fillWidth: true
                    label: root.i18n.catalog["columns.strategy"]
                    model: root.controller.candidateNames
                    enabled: !root.controller.busy && !operationRuntime.busy
                    onSelected: root.controller.selectCandidate(currentIndex)
                }
                Components.LabeledComboBox {
                    id: view
                    objectName: "intradayResearchView"
                    Layout.preferredWidth: 250
                    label: root.i18n.catalog["quant.intraday_result_view"]
                    readonly property int selectedView: root.controller.viewIndex
                    model: ["quant.intraday_overview", "quant.trades", "quant.intraday_ledger", "quant.intraday_daily",
                        "quant.intraday_models", "quant.intraday_predictions", "quant.intraday_contributions",
                        "quant.performance", "quant.performance_exit", "quant.performance_entry", "quant.performance_day",
                        "quant.risk_summary", "quant.risk_drawdowns", "quant.risk_distributions", "quant.risk_concentration",
                        "quant.risk_folds", "quant.parameter_grid", "quant.return_uncertainty",
                        "quant.family_bounds", "quant.sequential_selection", "quant.signal_delay",
                        "quant.prediction_quality"].map(key => root.i18n.catalog[key])
                    onSelected: root.controller.selectView(currentIndex)
                    onModelChanged: currentIndex = selectedView
                }
            }
            Label {
                Layout.fillWidth: true
                visible: root.controller.scenariosLoaded && view.selectedView === 0
                text: root.i18n.catalog["quant.scenarios_comparison_note"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            ColumnLayout {
                visible: root.controller.resultLoaded && view.selectedView === 0
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
            ColumnLayout {
                objectName: "intradayParameterGridPanel"
                Layout.fillWidth: true
                visible: view.selectedView === 16
                spacing: Theme.PixelTheme.spacingSm
                Label {
                    objectName: "intradayParameterGridNotice"
                    Layout.fillWidth: true
                    text: root.controller.gridAvailable ? root.i18n.catalog["grid.note"] : root.i18n.catalog["grid.diagnostics_only"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    Layout.fillWidth: true
                    visible: root.controller.gridError.length > 0
                    text: root.controller.gridError
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.ink
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: root.controller.gridAvailable
                    Components.LabeledComboBox {
                        id: gridCost
                        objectName: "intradayGridCost"
                        Layout.maximumWidth: 340
                        label: root.i18n.catalog["grid.cost"]
                        model: root.controller.gridCostNames
                        onSelected: root.controller.selectGridCost(currentIndex)
                        onModelChanged: currentIndex = root.controller.gridCostIndex
                    }
                    Components.LabeledComboBox {
                        id: gridMetric
                        objectName: "intradayGridMetric"
                        Layout.maximumWidth: 400
                        label: root.i18n.catalog["grid.metric"]
                        model: root.gridMetrics.map(key => root.gridLabel(key))
                        onSelected: root.controller.selectGridMetric(currentIndex)
                        onModelChanged: currentIndex = root.controller.gridMetricIndex
                    }
                }
                Label {
                    Layout.fillWidth: true
                    visible: !!root.gridData.center
                    text: (root.gridData.axes || []).map(axis => root.axisName(axis)).join("\n")
                        + "\n" + root.i18n.catalog["grid.order_note"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Flickable {
                    id: gridScroll
                    objectName: "intradayParameterGridScroll"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 234
                    visible: !!root.gridData.center
                    clip: true
                    contentWidth: cells.implicitWidth + 12
                    contentHeight: cells.implicitHeight + 12
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.horizontal: Components.PixelScrollBar {}
                    ScrollBar.vertical: Components.PixelScrollBar {}
                    Grid {
                        id: cells
                        spacing: 8
                        columns: (root.gridData.axes || []).length === 2 ? root.gridData.axes[1].values.length
                            : ((root.gridData.axes || []).length === 1 ? root.gridData.axes[0].values.length : 1)
                        Repeater {
                            model: root.gridData.cells || []
                            Components.PixelButton {
                                id: cellButton
                                required property var modelData
                                objectName: "intradayGridCell" + modelData.candidate_index
                                width: 280
                                height: Math.max(204, contentItem.implicitHeight + 24)
                                variant: root.gridData.selection && root.gridData.selection.center_candidate_index === modelData.candidate_index ? "primary" : "secondary"
                                Accessible.name: root.i18n.catalog["grid.candidate"] + " " + modelData.candidate_index + "; " + root.coordinates(modelData)
                                onClicked: root.controller.selectGridCandidate(modelData.candidate_index)
                                ToolTip.visible: hovered
                                ToolTip.text: modelData.candidate_id
                                contentItem: ColumnLayout {
                                    spacing: 4
                                    Label {
                                        Layout.fillWidth: true
                                        text: root.i18n.catalog["grid.candidate"] + " " + cellButton.modelData.candidate_index + " · " + cellButton.modelData.strategy_name
                                        wrapMode: Text.WrapAnywhere
                                        font.pixelSize: Theme.PixelTheme.fontMd
                                        font.bold: true
                                        color: Theme.PixelTheme.ink
                                    }
                                    Label {
                                        objectName: "intradayGridCoordinates" + cellButton.modelData.candidate_index
                                        Layout.fillWidth: true
                                        text: root.coordinates(cellButton.modelData, true)
                                        wrapMode: Text.WordWrap
                                        font.pixelSize: Theme.PixelTheme.fontSm
                                        color: Theme.PixelTheme.ink
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: root.gridAmount(cellButton.modelData.metric)
                                        wrapMode: Text.WrapAnywhere
                                        font.pixelSize: Theme.PixelTheme.fontMd
                                        color: Theme.PixelTheme.ink
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: root.gridLabel(cellButton.modelData.metric.evidence)
                                            + (cellButton.modelData.metric.unavailable_reason ? "\n" + root.gridLabel(cellButton.modelData.metric.unavailable_reason) : "")
                                        wrapMode: Text.WrapAnywhere
                                        font.pixelSize: Theme.PixelTheme.fontSm
                                        color: Theme.PixelTheme.inkMuted
                                    }
                                }
                            }
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: !!root.gridData.center
                    RowLayout {
                        Layout.fillWidth: true
                        Label {
                            Layout.fillWidth: true
                            text: root.i18n.catalog["grid.center"] + (root.gridData.selection ? " · "
                                + root.i18n.catalog["grid.cost_index"] + " " + root.gridData.selection.cost_index + " · "
                                + root.i18n.catalog["grid.candidate"] + " " + root.gridData.selection.center_candidate_index : "")
                            font.bold: true
                            wrapMode: Text.WordWrap
                            color: Theme.PixelTheme.ink
                        }
                        Components.PixelButton {
                            objectName: "intradayGridOpenDetails"
                            text: root.i18n.catalog["grid.open_details"]
                            onClicked: root.controller.openGridCandidateDetails()
                        }
                    }
                    Label {
                        objectName: "intradayGridCenterIdentity"
                        Layout.fillWidth: true
                        text: root.gridData.center ? root.i18n.catalog["quant.saved_experiment_id"] + ": " + root.gridData.experiment_id + "\n"
                            + root.i18n.catalog["quant.saved_candidate_id"] + ": " + root.gridData.center.candidate_id + "\n"
                            + root.coordinates(root.gridData.center) + "\n" + root.gridLabel(root.gridData.selection.metric) + ": "
                            + root.gridAmount(root.gridData.center.metric)
                            + (root.gridData.center.metric.unavailable_reason ? " · " + root.gridLabel(root.gridData.center.metric.unavailable_reason) : "") : ""
                        wrapMode: Text.WrapAnywhere
                        font.pixelSize: Theme.PixelTheme.fontSm
                        color: Theme.PixelTheme.ink
                    }
                    Label {
                        Layout.fillWidth: true
                        text: root.i18n.catalog["grid.neighbors"]
                        font.bold: true
                        wrapMode: Text.WordWrap
                        color: Theme.PixelTheme.ink
                    }
                    Label {
                        Layout.fillWidth: true
                        text: root.i18n.catalog["grid.neighbor_note"]
                        wrapMode: Text.WordWrap
                        font.pixelSize: Theme.PixelTheme.fontSm
                        color: Theme.PixelTheme.inkMuted
                    }
                    Repeater {
                        model: root.gridData.neighbors || []
                        Rectangle {
                            required property var modelData
                            id: neighborCard
                            objectName: "intradayGridNeighbor" + modelData.candidate_index
                            Layout.fillWidth: true
                            implicitHeight: neighborBody.implicitHeight + 16
                            color: Theme.PixelTheme.surfaceRaised
                            border.color: Theme.PixelTheme.line
                            ColumnLayout {
                                id: neighborBody
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 4
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label {
                                        Layout.fillWidth: true
                                        text: root.axisName(root.gridData.axes[neighborCard.modelData.axis_index]) + " · "
                                            + root.gridLabel(neighborCard.modelData.direction) + " · "
                                            + root.i18n.catalog["grid.candidate"] + " " + neighborCard.modelData.candidate_index
                                        wrapMode: Text.WordWrap
                                        color: Theme.PixelTheme.ink
                                        font.bold: true
                                        font.pixelSize: Theme.PixelTheme.fontSm
                                    }
                                    Components.PixelButton {
                                        objectName: "intradayGridSelectNeighbor" + neighborCard.modelData.candidate_index
                                        compact: true
                                        text: root.i18n.catalog["grid.select_center"]
                                        onClicked: root.controller.selectGridCandidate(neighborCard.modelData.candidate_index)
                                    }
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: root.coordinates(neighborCard.modelData) + "\n"
                                        + root.gridAmount(neighborCard.modelData.metric) + " · " + root.gridLabel(neighborCard.modelData.metric.evidence)
                                        + (neighborCard.modelData.metric.unavailable_reason ? " · " + root.gridLabel(neighborCard.modelData.metric.unavailable_reason) : "")
                                    wrapMode: Text.WrapAnywhere
                                    color: Theme.PixelTheme.ink
                                    font.pixelSize: Theme.PixelTheme.fontSm
                                }
                                Label {
                                    objectName: "intradayGridDelta" + neighborCard.modelData.candidate_index
                                    Layout.fillWidth: true
                                    text: root.i18n.catalog["grid.delta"] + ": " + root.gridAmount(neighborCard.modelData.delta)
                                        + (neighborCard.modelData.delta.unavailable_reason ? " · " + root.gridLabel(neighborCard.modelData.delta.unavailable_reason) : "")
                                        + (neighborCard.modelData.failed_basis_checks.length ? "\n" + root.i18n.catalog["grid.failed_basis"] + ": "
                                            + neighborCard.modelData.failed_basis_checks.map(key => root.gridLabel(key)).join(", ") : "")
                                    wrapMode: Text.WordWrap
                                    color: Theme.PixelTheme.inkMuted
                                    font.pixelSize: Theme.PixelTheme.fontSm
                                }
                            }
                        }
                    }
                    Label {
                        objectName: "intradayGridSummary"
                        Layout.fillWidth: true
                        text: {
                            const summary = root.gridData.neighborhood_summary
                            if (!summary) return ""
                            return root.i18n.catalog["grid.summary"] + "\n" + root.i18n.catalog["grid.neighbor_count"] + ": " + summary.neighbor_count
                                + " · " + root.i18n.catalog["grid.basis_matching_count"] + ": " + summary.basis_matching_count
                                + " · " + root.i18n.catalog["grid.available_count"] + ": " + summary.available_count + "\n"
                                + root.gridLabel("minimum") + ": " + summary.minimum_display + " · "
                                + root.gridLabel("p50") + ": " + summary.median_display + " · "
                                + root.gridLabel("maximum") + ": " + summary.maximum_display + " (" + root.gridLabel(summary.unit) + ")"
                                + (summary.unavailable_reason ? "\n" + root.gridLabel(summary.unavailable_reason) : "")
                        }
                        wrapMode: Text.WordWrap
                        color: Theme.PixelTheme.ink
                        font.pixelSize: Theme.PixelTheme.fontSm
                    }
                }
            }
            ColumnLayout {
                objectName: "intradayReturnUncertaintyPanel"
                Layout.fillWidth: true
                visible: view.selectedView === 17
                spacing: 4
                Label {
                    objectName: "intradayReturnUncertaintyNotice"
                    Layout.fillWidth: true
                    text: root.i18n.catalog[root.controller.uncertaintyAvailable ? "uncertainty.note" : "uncertainty.saved_only"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradayReturnUncertaintyParameters"
                    Layout.fillWidth: true
                    visible: !!root.uncertaintyData.sample
                    text: {
                        const data = root.uncertaintyData
                        if (!data.sample) return ""
                        const sample = data.sample, sampling = data.sampling
                        return root.i18n.catalog["uncertainty.samples"] + ": " + sample.sample_count
                            + " · " + sample.first_day + " → " + sample.last_day
                            + " · " + root.i18n.catalog["uncertainty.folds"] + ": " + sample.fold_count + "\n"
                            + root.i18n.catalog["uncertainty.block_days"] + ": " + sampling.block_days
                            + " (" + root.uncertaintyLabel(sampling.block_days_source) + ")"
                            + " · " + root.i18n.catalog["uncertainty.expected_blocks"] + ": " + Number(sampling.expected_block_count).toPrecision(6)
                            + " · " + root.i18n.catalog["uncertainty.replications"] + ": " + sampling.replications
                            + " · " + root.i18n.catalog["uncertainty.seed"] + ": " + sampling.seed
                            + " · " + root.uncertaintyLabel(sampling.prng) + "\n"
                            + root.i18n.catalog["uncertainty.unevaluated_days"] + ": " + sample.unevaluated_development_day_count
                            + " · " + root.i18n.catalog["uncertainty.predictions"] + ": " + sample.prediction_count
                            + " · " + root.i18n.catalog["uncertainty.complete_targets"] + ": "
                            + (sample.complete_target_count == null ? root.uncertaintyLabel(sample.complete_target_count_unavailable_reason)
                                : sample.complete_target_count)
                    }
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradayReturnUncertaintySelection"
                    Layout.fillWidth: true
                    visible: !!root.uncertaintyData.candidate_id
                    text: root.uncertaintyData.candidate_id ? root.i18n.catalog["uncertainty.saved_selection"]
                        + " · " + root.i18n.catalog["grid.cost_index"] + " " + root.uncertaintyData.cost_index
                        + " · " + root.i18n.catalog["grid.candidate"] + " " + root.uncertaintyData.candidate_index
                        + " · " + root.uncertaintyData.candidate_id.slice(0, 12) : ""
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                    ToolTip.visible: uncertaintyHover.hovered
                    ToolTip.text: root.controller.experimentPath + "\n" + (root.uncertaintyData.experiment_id || "")
                        + "\n" + (root.uncertaintyData.candidate_id || "")
                    HoverHandler { id: uncertaintyHover }
                }
                Label {
                    objectName: "intradayReturnUncertaintyProgress"
                    Layout.fillWidth: true
                    visible: root.controller.uncertaintyAvailable && !root.uncertaintyData.sample && !root.controller.uncertaintyError
                    text: root.i18n.catalog["uncertainty.calculating"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: root.controller.uncertaintyError.length > 0
                    Label {
                        objectName: "intradayReturnUncertaintyError"
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: root.controller.uncertaintyError
                        wrapMode: Text.WrapAnywhere
                        color: Theme.PixelTheme.ink
                        font.pixelSize: Theme.PixelTheme.fontSm
                    }
                    Components.PixelButton {
                        objectName: "intradayReturnUncertaintyRetry"
                        text: root.i18n.catalog["uncertainty.retry"]
                        enabled: !root.controller.busy && !operationRuntime.busy
                        onClicked: root.controller.retryUncertainty()
                    }
                }
            }
            ColumnLayout {
                objectName: "intradayFamilyBoundsPanel"
                Layout.fillWidth: true
                visible: view.selectedView === 18
                spacing: 4
                Label {
                    objectName: "intradayFamilyBoundsNotice"
                    Layout.fillWidth: true
                    text: root.i18n.catalog[root.controller.familyBoundsAvailable ? "family_bounds.note" : "uncertainty.saved_only"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradayFamilyBoundsScope"
                    Layout.fillWidth: true
                    visible: !!root.familyData.sample
                    text: {
                        const data = root.familyData
                        if (!data.sample) return ""
                        return root.i18n.catalog["grid.cost_index"] + " " + data.cost_index
                            + " · " + root.i18n.catalog["family_bounds.count"] + ": " + data.family_size
                            + " · " + root.familyLabel(data.family_scope) + "\n"
                            + root.i18n.catalog["family_bounds.history"] + ": " + root.familyLabel(data.historical_search_coverage)
                            + ". " + root.i18n.catalog["family_bounds.selection"]
                    }
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                    ToolTip.visible: familyHover.hovered
                    ToolTip.text: root.controller.experimentPath + "\n" + (root.familyData.experiment_id || "")
                        + "\n" + (root.familyData.data_id || "") + "\n"
                        + (root.familyData.members || []).map(member => member.candidate_index + " · "
                            + member.strategy.name + " · " + member.candidate_id).join("\n")
                    HoverHandler { id: familyHover }
                }
                Label {
                    objectName: "intradayFamilyBoundsParameters"
                    Layout.fillWidth: true
                    visible: !!root.familyData.sample
                    text: {
                        const data = root.familyData
                        if (!data.sample) return ""
                        const sample = data.sample, sampling = data.sampling
                        return root.i18n.catalog["uncertainty.samples"] + ": " + sample.sample_count
                            + " · " + sample.first_day + " → " + sample.last_day
                            + " · " + root.i18n.catalog["uncertainty.folds"] + ": " + sample.fold_count
                            + " · " + root.i18n.catalog["uncertainty.unevaluated_days"] + ": " + sample.unevaluated_development_day_count + "\n"
                            + root.i18n.catalog["uncertainty.block_days"] + ": " + sampling.block_days
                            + " (" + root.uncertaintyLabel(sampling.block_days_source) + ")"
                            + " · " + root.i18n.catalog["uncertainty.expected_blocks"] + ": " + Number(sampling.expected_block_count).toPrecision(6)
                            + " · " + root.i18n.catalog["uncertainty.replications"] + ": " + sampling.replications
                            + " · " + root.i18n.catalog["uncertainty.seed"] + ": " + sampling.seed
                            + " · " + root.uncertaintyLabel(sampling.prng)
                    }
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradayFamilyBoundsInference"
                    Layout.fillWidth: true
                    visible: !!root.familyData.sample
                    text: {
                        const data = root.familyData
                        if (!data.sample) return ""
                        const inference = data.family_inference
                        return root.i18n.catalog["family_bounds.inference"] + ": " + root.familyLabel(inference.status)
                            + (inference.reason ? " · " + root.familyLabel(inference.reason) : "")
                            + " · " + root.i18n.catalog["family_bounds.deduction"] + ": " + data.deduction_display
                            + " " + root.uncertaintyLabel("PERCENTAGE_POINTS")
                    }
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                    ToolTip.visible: familyInferenceHover.hovered
                    ToolTip.text: root.familyData.family_inference ? (root.familyData.family_inference.detail || "") : ""
                    HoverHandler { id: familyInferenceHover }
                }
                Label {
                    objectName: "intradayFamilyBoundsProgress"
                    Layout.fillWidth: true
                    visible: root.controller.familyBoundsAvailable && !root.familyData.sample && !root.controller.familyBoundsError
                    text: root.i18n.catalog["family_bounds.calculating"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: root.controller.familyBoundsError.length > 0
                    Label {
                        objectName: "intradayFamilyBoundsError"
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: root.controller.familyBoundsError
                        wrapMode: Text.WrapAnywhere
                        color: Theme.PixelTheme.ink
                        font.pixelSize: Theme.PixelTheme.fontSm
                    }
                    Components.PixelButton {
                        objectName: "intradayFamilyBoundsRetry"
                        text: root.i18n.catalog["uncertainty.retry"]
                        enabled: !root.controller.busy && !operationRuntime.busy
                        onClicked: root.controller.retryFamilyBounds()
                    }
                }
            }
            ColumnLayout {
                objectName: "intradaySequentialPanel"
                Layout.fillWidth: true
                visible: view.selectedView === 19
                spacing: 4
                Label {
                    objectName: "intradaySequentialNotice"
                    Layout.fillWidth: true
                    text: root.i18n.catalog[root.controller.sequentialAvailable ? "sequential.note" : "sequential.saved_only"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySequentialScope"
                    Layout.fillWidth: true
                    visible: !!root.sequentialData.sample
                    text: {
                        const data = root.sequentialData
                        if (!data.sample) return ""
                        return root.i18n.catalog["grid.cost_index"] + " " + data.cost_index
                            + " · " + root.i18n.catalog["family_bounds.count"] + ": " + data.family_size
                            + " · " + root.familyLabel(data.family_scope) + "\n"
                            + root.i18n.catalog["family_bounds.history"] + ": " + root.familyLabel(data.historical_search_coverage)
                            + " · " + root.i18n.catalog["sequential.precommitment"] + ": " + root.familyLabel(data.family_precommitment) + "\n"
                            + root.i18n.catalog["sequential.minimum_history"] + ": " + data.selection_rule.minimum_history_days
                    }
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySequentialSample"
                    Layout.fillWidth: true
                    visible: !!root.sequentialData.sample
                    text: {
                        const data = root.sequentialData
                        if (!data.sample) return ""
                        const source = data.source_sample, sample = data.sample
                        return root.i18n.catalog["sequential.source_sample"] + ": " + source.sample_count
                            + " · " + source.first_day + " → " + source.last_day + "\n"
                            + root.i18n.catalog["sequential.warmup"] + ": " + sample.warmup_days.length
                            + " · " + root.i18n.catalog["sequential.following_sample"] + ": " + (sample.sample_count == null ? "—" : sample.sample_count)
                            + " · " + (sample.first_day || "—") + " → " + (sample.last_day || "—") + "\n"
                            + root.i18n.catalog["sequential.selections"] + ": " + (data.selection_summary.selection_count == null ? "—" : data.selection_summary.selection_count)
                            + " · " + root.i18n.catalog["sequential.switches"] + ": " + (data.selection_summary.switch_count == null ? "—" : data.selection_summary.switch_count)
                    }
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySequentialAvailability"
                    Layout.fillWidth: true
                    visible: !!root.sequentialData.availability
                    text: {
                        const data = root.sequentialData
                        if (!data.availability) return ""
                        const available = data.availability
                        return root.sequentialLabel(available.status)
                            + (available.unavailable_reason ? " · " + root.sequentialLabel(available.unavailable_reason) : "")
                            + (available.detail ? "\n" + available.detail : "")
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySequentialProgress"
                    Layout.fillWidth: true
                    visible: root.controller.sequentialAvailable && !root.sequentialData.sample && !root.controller.sequentialError
                    text: root.i18n.catalog["sequential.calculating"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: root.controller.sequentialError.length > 0
                    Label {
                        objectName: "intradaySequentialError"
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: root.controller.sequentialError
                        wrapMode: Text.WrapAnywhere
                        color: Theme.PixelTheme.ink
                        font.pixelSize: Theme.PixelTheme.fontSm
                    }
                    Components.PixelButton {
                        objectName: "intradaySequentialRetry"
                        text: root.i18n.catalog["uncertainty.retry"]
                        enabled: !root.controller.busy && !operationRuntime.busy
                        onClicked: root.controller.retrySequential()
                    }
                }
                Components.LabeledComboBox {
                    objectName: "intradaySequentialView"
                    Layout.fillWidth: true
                    Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["sequential.view"]
                    model: ["summary", "timeline", "scores", "references", "daily", "path"].map(key => root.i18n.catalog["sequential." + key])
                    currentIndex: root.controller.sequentialViewIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.sequentialViewIndex)
                    onSelected: root.controller.selectSequentialView(currentIndex)
                }
                Label {
                    objectName: "intradaySequentialViewNote"
                    Layout.fillWidth: true
                    text: root.i18n.catalog["sequential." + ["summary", "timeline", "scores", "references", "daily", "path"][root.controller.sequentialViewIndex] + "_note"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
            ColumnLayout {
                objectName: "intradaySignalDelayPanel"
                Layout.fillWidth: true
                visible: view.selectedView === 20
                spacing: 4
                Label {
                    objectName: "intradaySignalDelayNotice"
                    Layout.fillWidth: true
                    text: root.i18n.catalog[root.controller.signalDelayAvailable ? "signal_delay.note" : "signal_delay.saved_only"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySignalDelayScope"
                    Layout.fillWidth: true
                    visible: !!root.signalDelayData.sample
                    text: {
                        const data = root.signalDelayData
                        if (!data.sample) return ""
                        const sample = data.sample
                        return data.strategy.name + " · " + root.i18n.catalog["grid.cost_index"] + " " + data.cost_index
                            + " · " + root.i18n.catalog["signal_delay.candidate_index"] + " " + data.candidate_index
                            + "\n" + root.i18n.catalog["sequential.source_sample"] + ": " + sample.sample_count
                            + " · " + sample.first_day + " → " + sample.last_day
                            + " · " + root.i18n.catalog["risk.fold_count"] + ": " + sample.fold_count
                            + " · " + root.i18n.catalog["signal_delay.gaps"] + ": " + sample.gap_days.length
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySignalDelayAvailability"
                    Layout.fillWidth: true
                    visible: !!root.signalDelayData.availability
                    text: {
                        const data = root.signalDelayData
                        if (!data.availability) return ""
                        return root.i18n.catalog["signal_delay.analysis"] + ": " + root.signalDelayStatus(data.availability)
                            + "\n" + root.i18n.catalog["signal_delay.baseline"] + ": " + root.signalDelayStatus(data.baseline)
                            + "\n" + data.scenarios.map(row => root.i18n.catalog["signal_delay.delay"] + " " + row.delay_bars
                                + ": " + root.signalDelayStatus(row)).join(" · ")
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySignalDelayProgress"
                    Layout.fillWidth: true
                    visible: root.controller.signalDelayAvailable && !root.signalDelayData.sample && !root.controller.signalDelayError
                    text: root.i18n.catalog["signal_delay.calculating"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: root.controller.signalDelayError.length > 0
                    Label {
                        objectName: "intradaySignalDelayError"
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: root.controller.signalDelayError
                        wrapMode: Text.WrapAnywhere
                        color: Theme.PixelTheme.ink
                        font.pixelSize: Theme.PixelTheme.fontSm
                    }
                    Components.PixelButton {
                        objectName: "intradaySignalDelayRetry"
                        text: root.i18n.catalog["uncertainty.retry"]
                        enabled: !root.controller.busy && !operationRuntime.busy
                        onClicked: root.controller.retrySignalDelay()
                    }
                }
                Components.LabeledComboBox {
                    objectName: "intradaySignalDelayView"
                    Layout.fillWidth: true
                    Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["signal_delay.view"]
                    model: ["summary", "daily", "trades", "path", "provenance"].map(key => root.i18n.catalog["signal_delay." + key])
                    currentIndex: root.controller.signalDelayViewIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.signalDelayViewIndex)
                    onSelected: root.controller.selectSignalDelayView(currentIndex)
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: root.controller.signalDelayViewIndex > 0
                    Components.LabeledComboBox {
                        objectName: "intradaySignalDelayScenario"
                        Layout.maximumWidth: Infinity
                        label: root.i18n.catalog["signal_delay.delay"]
                        model: [0, 1, 2].map(value => value + " · " + root.i18n.catalog["performance.BARS"])
                        currentIndex: root.controller.signalDelayScenarioIndex
                        onModelChanged: currentIndex = Qt.binding(() => root.controller.signalDelayScenarioIndex)
                        onSelected: root.controller.selectSignalDelayDetail(currentIndex, root.controller.signalDelayAccountIndex)
                    }
                    Components.LabeledComboBox {
                        objectName: "intradaySignalDelayAccount"
                        Layout.maximumWidth: Infinity
                        label: root.i18n.catalog["columns.risk_series"]
                        model: ["STRATEGY", "BENCHMARK"].map(key => root.signalDelayLabel(key))
                        currentIndex: root.controller.signalDelayAccountIndex
                        onModelChanged: currentIndex = Qt.binding(() => root.controller.signalDelayAccountIndex)
                        onSelected: root.controller.selectSignalDelayDetail(root.controller.signalDelayScenarioIndex, currentIndex)
                    }
                }
                Label {
                    objectName: "intradaySignalDelayViewNote"
                    Layout.fillWidth: true
                    text: root.i18n.catalog["signal_delay." + ["summary", "daily", "trades", "path", "provenance"][root.controller.signalDelayViewIndex] + "_note"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySignalDelayDetailStatus"
                    Layout.fillWidth: true
                    visible: root.controller.signalDelayViewIndex > 0 && !!root.signalDelayDetail.signals
                    text: {
                        const detail = root.signalDelayDetail
                        if (!detail.signals) return ""
                        return root.signalDelayStatus(detail) + "\n"
                            + Object.keys(detail.signals).map(key => root.signalDelayLabel(key) + ": " + detail.signals[key]).join(" · ")
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
            ColumnLayout {
                objectName: "intradayPredictionQualityPanel"
                Layout.fillWidth: true
                visible: view.selectedView === 21
                spacing: Theme.PixelTheme.spacingSm
                Label {
                    objectName: "intradayPredictionQualityNotice"
                    Layout.fillWidth: true
                    text: root.i18n.catalog[root.controller.predictionQualityAvailable
                        ? "prediction_quality.note" : "prediction_quality.saved_only"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                RowLayout {
                    Layout.fillWidth: true
                    Components.LabeledTextField {
                        id: predictionSource
                        objectName: "intradayPredictionSource"
                        Layout.fillWidth: true
                        Layout.maximumWidth: Infinity
                        label: root.i18n.catalog["prediction_quality.source"]
                        placeholderText: root.i18n.catalog["prediction_quality.recorded_source"]
                        onEdited: value => root.controller.setPredictionQualitySource(value)
                    }
                    Components.PixelButton {
                        objectName: "intradayPredictionLocateButton"
                        Layout.alignment: Qt.AlignBottom
                        text: root.i18n.catalog["prediction_quality.locate"]
                        onClicked: predictionSourceDialog.open()
                    }
                    Components.PixelButton {
                        objectName: "intradayPredictionAnalyzeButton"
                        Layout.alignment: Qt.AlignBottom
                        text: root.i18n.catalog[root.predictionData.sample ? "prediction_quality.refresh" : "prediction_quality.analyze"]
                        variant: "primary"
                        enabled: root.controller.predictionQualityAvailable && !root.controller.busy && !operationRuntime.busy
                        onClicked: root.controller.analyzePredictionQuality()
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: root.i18n.catalog["prediction_quality.source_note"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradayPredictionPending"
                    Layout.fillWidth: true
                    visible: root.controller.predictionQualityPending
                    text: root.i18n.catalog["prediction_quality.calculating"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradayPredictionError"
                    Layout.fillWidth: true
                    visible: root.controller.predictionQualityError.length > 0
                    text: root.controller.predictionQualityError + "\n" + root.i18n.catalog["prediction_quality.retry_note"]
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradayPredictionCompletedSource"
                    Layout.fillWidth: true
                    visible: !!root.predictionData.sample
                    text: !root.predictionData.sample ? "" : root.i18n.catalog["prediction_quality.completed_source"]
                        + ": " + root.controller.predictionQualityCompletedSource.data_path
                        + "\n" + root.predictionData.strategy.name + " · "
                        + root.i18n.catalog["prediction_quality.cost_index"] + " " + root.predictionData.cost_index
                        + " · " + root.i18n.catalog["prediction_quality.candidate_index"] + " " + root.predictionData.candidate_index
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradayPredictionDraftChanged"
                    Layout.fillWidth: true
                    visible: root.controller.predictionQualityDraftChanged
                    text: root.i18n.catalog["prediction_quality.draft_changed"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradayPredictionCoverage"
                    Layout.fillWidth: true
                    visible: !!root.predictionData.sample
                    text: {
                        const sample = root.predictionData.sample
                        if (!sample) return ""
                        return root.i18n.catalog["prediction_quality.reconstructed"] + "\n"
                            + root.i18n.catalog["prediction_quality.ready"] + ": " + sample.prediction_count
                            + " · " + root.i18n.catalog["prediction_quality.complete"] + ": " + sample.complete_target_count
                            + " · " + root.i18n.catalog["prediction_quality.incomplete"] + ": " + sample.incomplete_target_count
                            + " · " + root.i18n.catalog["prediction_quality.scored_days"] + ": " + sample.scored_day_count
                            + " / " + sample.evaluated_day_count
                            + " · " + root.i18n.catalog["prediction_quality.folds"] + ": " + sample.fold_count
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: !!root.predictionData.sample
                    Components.LabeledComboBox {
                        objectName: "intradayPredictionView"
                        Layout.fillWidth: true
                        label: root.i18n.catalog["prediction_quality.view"]
                        model: ["pooled", "fold", "predictions"].map(key => root.predictionLabel(key))
                        currentIndex: root.controller.predictionQualityViewIndex
                        onModelChanged: currentIndex = Qt.binding(() => root.controller.predictionQualityViewIndex)
                        onSelected: root.controller.selectPredictionQualityView(currentIndex)
                    }
                    Components.LabeledComboBox {
                        objectName: "intradayPredictionFold"
                        Layout.fillWidth: true
                        visible: root.controller.predictionQualityViewIndex === 1
                        label: root.i18n.catalog["prediction_quality.fold"]
                        model: (root.predictionData.folds || []).map(fold => fold.fold_index + " · "
                            + fold.validation_days[0] + " → " + fold.validation_days[fold.validation_days.length - 1])
                        currentIndex: root.controller.predictionQualityFoldIndex
                        onModelChanged: currentIndex = Qt.binding(() => root.controller.predictionQualityFoldIndex)
                        onSelected: root.controller.selectPredictionQualityFold(currentIndex)
                    }
                }
                Label {
                    objectName: "intradayPredictionFoldCoverage"
                    Layout.fillWidth: true
                    visible: root.controller.predictionQualityViewIndex === 1 && !!root.predictionFold.sample
                    text: !root.predictionFold.sample ? "" : root.i18n.catalog["prediction_quality.training_count"]
                        + ": " + root.predictionFold.training_count
                        + " · " + root.i18n.catalog["prediction_quality.ready"] + ": " + root.predictionFold.sample.prediction_count
                        + " · " + root.i18n.catalog["prediction_quality.complete"] + ": " + root.predictionFold.sample.complete_target_count
                        + "\n" + root.i18n.catalog["prediction_quality.training_boundary"] + ": " + root.predictionFold.training_boundary
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradayPredictionViewNote"
                    Layout.fillWidth: true
                    visible: !!root.predictionData.sample
                    text: root.i18n.catalog["prediction_quality."
                        + ["pooled", "fold", "predictions"][root.controller.predictionQualityViewIndex] + "_note"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
            Components.DataTable {
                objectName: "intradayResearchTable"
                visible: view.selectedView !== 16
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: view.selectedView === 0 ? 120 : 170
                paged: true
                tableModel: root.controller.tableModel
                i18n: root.i18n
                cellFormatter: function(value) {
                    if (view.selectedView === 21) return root.predictionLabel(value)
                    if (view.selectedView === 20) return root.signalDelayLabel(value)
                    if (view.selectedView === 19) return root.sequentialLabel(value)
                    if (view.selectedView === 18) return root.familyLabel(value)
                    if (view.selectedView === 17) return root.uncertaintyLabel(value)
                    if (view.selectedView >= 11) return root.i18n.catalog["risk." + value] || root.i18n.catalog["performance." + value] || value
                    return view.selectedView >= 7 ? (root.i18n.catalog["performance." + value] || value) : value
                }
                onPreviousRequested: root.controller.changePage(-1)
                onNextRequested: root.controller.changePage(1)
            }
            Components.PixelButton {
                objectName: "intradayPredictionDetailsButton"
                visible: view.selectedView === 21 && !!root.predictionData.sample
                text: root.i18n.catalog["prediction_quality.details"]
                onClicked: root.showPredictionDetails = !root.showPredictionDetails
            }
            Label {
                objectName: "intradayPredictionDetails"
                visible: view.selectedView === 21 && root.showPredictionDetails && !!root.predictionData.sample
                Layout.fillWidth: true
                text: {
                    const data = root.predictionData
                    if (!data.sample) return ""
                    return root.controller.predictionQualityCompletedSource.experiment_path + "\n"
                        + ["prediction_quality_id", "version", "experiment_id", "data_id", "research_id", "candidate_id"]
                            .map(key => root.predictionLabel(key) + ": " + data[key]).join("\n")
                        + "\n" + root.predictionLabel("features") + ": " + data.feature_fields.join(", ")
                        + " · " + root.predictionLabel("horizon") + ": " + data.target_horizon_bars
                        + "\n" + root.predictionLabel("recorded_locator") + ": " + data.source_locator.recorded
                        + "\n" + root.predictionLabel("used_locator") + ": " + data.source_locator.used
                        + "\n" + root.predictionLabel("evidence") + ": " + JSON.stringify(data.evidence)
                        + "\n" + root.predictionLabel("method") + ": " + JSON.stringify(data.method)
                        + "\n" + root.predictionLabel("fold_ids") + ": " + data.folds.map(fold => fold.fold_index
                            + " · " + fold.fold_id + " · " + fold.model_id).join("\n")
                        + "\n" + root.predictionLabel("metric_details") + " · "
                        + (root.controller.predictionQualityViewIndex === 1 ? root.predictionLabel("fold")
                            + " " + root.controller.predictionQualityFoldIndex : root.predictionLabel("pooled")) + ":\n"
                        + root.controller.predictionQualityMetricDetails.map(row => root.predictionLabel(row.forecast)
                            + " · " + root.predictionLabel(row.metric) + ": " + row.value
                            + " (" + root.predictionLabel(row.unit) + ")"
                            + (row.reason ? " · " + root.predictionLabel(row.reason) : "")).join("\n")
                }
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.LabeledComboBox {
                objectName: "intradaySignalDelaySignalPicker"
                visible: view.selectedView === 20 && root.controller.signalDelayViewIndex === 4 && model.length > 0
                Layout.fillWidth: true
                Layout.maximumWidth: Infinity
                label: root.i18n.catalog["signal_delay.signal_details"]
                model: root.controller.signalDelaySignalNames
                currentIndex: root.controller.signalDelaySignalIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.signalDelaySignalIndex)
                onSelected: root.controller.selectSignalDelaySignal(currentIndex)
            }
            Label {
                objectName: "intradaySignalDelaySignalDetails"
                visible: view.selectedView === 20 && root.controller.signalDelayViewIndex === 4
                Layout.fillWidth: true
                text: {
                    const signal = root.signalDelayDetail.signal || ({})
                    if (!signal.source_observation_key) return ""
                    return ["source_observation_key", "source_trading_day", "source_slot", "source_time", "source_target",
                        "source_score", "delay_bars", "arrival_slot", "arrival_time", "derived_decision_key", "status", "passed_to_kernel"]
                        .map(key => root.signalDelayLabel(key) + ": " + (signal[key] == null ? "—"
                            : typeof signal[key] === "boolean" ? root.signalDelayLabel(signal[key] ? "YES" : "NO")
                            : root.signalDelayLabel(String(signal[key])))).join("\n")
                }
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.PixelButton {
                objectName: "intradaySignalDelayDetailsButton"
                visible: view.selectedView === 20 && !!root.signalDelayData.sample
                text: root.i18n.catalog["signal_delay.details"]
                onClicked: root.showSignalDelayDetails = !root.showSignalDelayDetails
            }
            ColumnLayout {
                objectName: "intradaySignalDelayDetails"
                Layout.fillWidth: true
                visible: view.selectedView === 20 && root.showSignalDelayDetails && !!root.signalDelayData.sample
                spacing: 4
                Label {
                    objectName: "intradaySignalDelayIdentities"
                    Layout.fillWidth: true
                    text: {
                        const data = root.signalDelayData
                        if (!data.sample) return ""
                        return root.controller.experimentPath + "\n"
                            + ["signal_delay_id", "version", "experiment_id", "data_id", "research_id", "context_id", "candidate_id", "evidence"]
                                .map(key => root.signalDelayLabel(key) + ": " + data[key]).join("\n")
                            + "\n" + root.i18n.catalog["signal_delay.features"] + ": " + data.feature_fields.join(", ")
                            + "\n" + root.i18n.catalog["signal_delay.versions"] + ": " + JSON.stringify(data.algorithm_versions)
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySignalDelayProjection"
                    Layout.fillWidth: true
                    text: {
                        const data = root.signalDelayData
                        if (!data.projection) return ""
                        const projection = data.projection
                        return root.i18n.catalog["signal_delay.projection"] + ": " + root.signalDelayStatus(projection)
                            + "\n" + ["source_strategy_price_evidence_id", "source_benchmark_price_evidence_id", "reconstructed_price_evidence_id"]
                                .map(key => root.signalDelayLabel(key) + ": " + (projection[key] || "—")).join("\n")
                            + "\n" + root.i18n.catalog["signal_delay.session_fields"] + ": " + projection.session_fields.join(", ")
                            + "\n" + root.i18n.catalog["signal_delay.price_fields"] + ": " + projection.price_fields.join(", ")
                            + "\n" + root.i18n.catalog["signal_delay.basis"] + ": " + root.signalDelayLabel(data.basis.matches ? "YES" : "NO")
                            + " · " + JSON.stringify(data.basis.failed_checks)
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySignalDelayBaseline"
                    Layout.fillWidth: true
                    text: {
                        const data = root.signalDelayData
                        if (!data.baseline) return ""
                        return root.i18n.catalog["signal_delay.baseline_note"] + "\n"
                            + root.i18n.catalog["signal_delay.excluded_fields"] + ": " + data.baseline.excluded_identity_fields.join(", ")
                            + "\n" + data.baseline.accounts.map(check => root.signalDelayLabel(check.account) + ": "
                                + root.signalDelayStatus(check) + "\n"
                                + ["source_execution_id", "source_price_evidence_id", "reexecuted_execution_id", "reconstructed_price_evidence_id"]
                                    .map(key => root.signalDelayLabel(key) + ": " + (check[key] || "—")).join("\n")
                                + "\n" + root.i18n.catalog["signal_delay.differing_fields"] + ": " + (check.differing_fields.join(", ") || "—")
                                ).join("\n\n")
                            + "\n\n" + data.availability.accounts.map(check => root.signalDelayLabel(check.account) + " · "
                                + root.i18n.catalog["signal_delay.source_account"] + ": " + root.signalDelayStatus(check)).join("\n")
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySignalDelayPolicies"
                    Layout.fillWidth: true
                    text: {
                        const data = root.signalDelayData, detail = root.signalDelayDetail
                        if (!data.sample) return ""
                        return ["execution_policy", "benchmark_execution_policy"].map((key, i) =>
                            root.signalDelayLabel(i ? "BENCHMARK" : "STRATEGY") + ": "
                            + Object.keys(data[key]).map(field => (root.i18n.catalog["columns." + field] || field)
                                + " = " + data[key][field]).join(" · ")).join("\n")
                            + "\n" + root.i18n.catalog["signal_delay.selected_execution"] + " (" + detail.delay_bars
                            + " · " + root.signalDelayLabel(detail.account) + "): " + (detail.execution_id || "—")
                            + "\n" + root.i18n.catalog["signal_delay.reconstructed_price_evidence_id"] + ": " + (detail.price_evidence_id || "—")
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySignalDelaySampleDetails"
                    Layout.fillWidth: true
                    text: {
                        const sample = root.signalDelayData.sample
                        if (!sample) return ""
                        return root.i18n.catalog["signal_delay.evaluated_days"] + ": " + sample.evaluated_days.join(", ")
                            + "\n" + root.i18n.catalog["signal_delay.gaps"] + ": " + (sample.gap_days.join(", ") || "—")
                            + "\n" + root.i18n.catalog["signal_delay.unevaluated_days"] + ": " + (sample.unevaluated_development_days.join(", ") || "—")
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
            Components.PixelButton {
                objectName: "intradaySequentialDetailsButton"
                visible: view.selectedView === 19 && !!root.sequentialData.sample
                text: root.i18n.catalog["sequential.details"]
                onClicked: root.showSequentialDetails = !root.showSequentialDetails
            }
            ColumnLayout {
                objectName: "intradaySequentialDetails"
                Layout.fillWidth: true
                visible: view.selectedView === 19 && root.showSequentialDetails && !!root.sequentialData.sample
                spacing: 4
                Label {
                    objectName: "intradaySequentialIdentities"
                    Layout.fillWidth: true
                    text: root.sequentialData.sample ? root.controller.experimentPath + "\n"
                        + root.i18n.catalog["sequential.report_id"] + ": " + root.sequentialData.sequential_selection_id + "\n"
                        + root.i18n.catalog["sequential.experiment_id"] + ": " + root.sequentialData.experiment_id + "\n"
                        + "Data ID: " + root.sequentialData.data_id + "\n"
                        + (root.sequentialData.members || []).map(member => member.candidate_index + " · "
                            + member.strategy.name + " · " + member.candidate_id).join("\n") : ""
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Components.LabeledComboBox {
                    id: sequentialFoldPicker
                    objectName: "intradaySequentialFoldPicker"
                    Layout.fillWidth: true
                    Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["sequential.fold_details"]
                    model: (root.sequentialData.folds || []).map(fold => fold.fold_index + " · "
                        + fold.validation_days[0] + " → " + fold.validation_days[fold.validation_days.length - 1])
                }
                Label {
                    objectName: "intradaySequentialPolicies"
                    Layout.fillWidth: true
                    text: root.sequentialData.sample ? ["execution_policy", "benchmark_execution_policy"].map((key, i) =>
                        root.sequentialLabel(i ? "BENCHMARK" : "STRATEGY") + ": "
                        + Object.keys(root.sequentialData[key]).map(field => (root.i18n.catalog["columns." + field] || field)
                            + " = " + root.sequentialData[key][field]).join(" · ")).join("\n") : ""
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Label {
                    objectName: "intradaySequentialFoldDetails"
                    Layout.fillWidth: true
                    text: {
                        const fold = root.sequentialFold
                        if (!fold.fold_id) return ""
                        return root.sequentialLabel(fold.status) + (fold.unavailable_reason ? " · " + root.sequentialLabel(fold.unavailable_reason) : "")
                            + "\n" + root.i18n.catalog["sequential.fold_id"] + ": " + fold.fold_id
                            + "\n" + root.i18n.catalog["sequential.training_boundary"] + ": " + fold.training_boundary
                            + "\n" + root.i18n.catalog["sequential.history_dates"] + " (" + fold.history_day_count + "): " + (fold.history_days.join(", ") || "—")
                            + "\n" + root.i18n.catalog["sequential.chosen_id"] + ": " + (fold.chosen_candidate_id || "—")
                            + "\n" + root.i18n.catalog["sequential.model_id"] + ": " + (fold.chosen_model_id || "—")
                            + "\n" + Object.keys(fold.outcome).map(key => root.sequentialLabel(key) + ": " + fold.outcome[key].display
                                + (fold.outcome[key].unavailable_reason ? " · " + root.sequentialLabel(fold.outcome[key].unavailable_reason) : "")).join("\n")
                    }
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                visible: view.selectedView === 18 && root.controller.familyBoundsAvailable
                spacing: 4
                Label {
                    objectName: "intradayFamilyBoundsUnits"
                    Layout.fillWidth: true
                    text: root.i18n.catalog["family_bounds.units"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Repeater {
                    model: (root.familyData.members || []).filter(member => member.mean_unavailable_reason)
                    Label {
                        required property var modelData
                        objectName: "intradayFamilyBoundsWarning" + modelData.candidate_index
                        Layout.fillWidth: true
                        text: root.i18n.catalog["grid.candidate"] + " " + modelData.candidate_index
                            + ": " + root.familyLabel(modelData.mean_unavailable_reason)
                        wrapMode: Text.WordWrap
                        color: Theme.PixelTheme.inkMuted
                        font.pixelSize: Theme.PixelTheme.fontSm
                        ToolTip.visible: familyWarningHover.hovered
                        ToolTip.text: modelData.detail || ""
                        HoverHandler { id: familyWarningHover }
                    }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                visible: view.selectedView === 17 && root.controller.uncertaintyAvailable
                spacing: 4
                Label {
                    objectName: "intradayReturnUncertaintyUnits"
                    Layout.fillWidth: true
                    text: root.i18n.catalog["uncertainty.units"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Repeater {
                    model: root.uncertaintyData.warnings || []
                    Label {
                        required property var modelData
                        objectName: "intradayReturnUncertaintyWarning" + modelData.series
                        Layout.fillWidth: true
                        text: root.uncertaintyLabel(modelData.series) + ": "
                            + modelData.reasons.map(reason => root.uncertaintyLabel(reason)).join("; ")
                        wrapMode: Text.WordWrap
                        color: Theme.PixelTheme.inkMuted
                        font.pixelSize: Theme.PixelTheme.fontSm
                        ToolTip.visible: warningHover.hovered
                        ToolTip.text: modelData.detail || ""
                        HoverHandler { id: warningHover }
                    }
                }
            }
            Label {
                Layout.fillWidth: true
                visible: view.selectedView >= 7 && view.selectedView < 16
                text: {
                    if (view.selectedView < 11) return root.i18n.catalog["quant.performance_note"]
                    const note = ["", "quant.risk_drawdowns_note", "quant.risk_distributions_note",
                        "quant.risk_concentration_note", "quant.risk_folds_note"][view.selectedView - 11]
                    return root.i18n.catalog["quant.risk_note"] + (note ? "\n" + root.i18n.catalog[note] : "")
                }
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
        }
    }
}
