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
    readonly property var gridData: root.controller.parameterGrid
    readonly property var gridMetrics: ["total_return", "observed_max_drawdown", "trade_count",
        "worst_fold_return", "median_fold_return", "best_fold_return"]

    function gridLabel(key) {
        return root.i18n.catalog["grid." + key] || root.i18n.catalog["risk." + key]
            || root.i18n.catalog["comparison." + key] || root.i18n.catalog["performance." + key]
            || root.i18n.catalog["columns." + key] || key
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
        scenario.currentIndex = root.controller.scenarioIndex
        candidate.currentIndex = root.controller.candidateIndex
        view.currentIndex = root.controller.viewIndex
        gridCost.currentIndex = root.controller.gridCostIndex
        gridMetric.currentIndex = root.controller.gridMetricIndex
        equity.requestPaint()
    }
    Component.onCompleted: sync()
    Connections { target: root.controller; function onChanged() { root.sync() } }

    IntradayResearchSettings { id: settings; i18n: root.i18n }
    IntradayExecutionScenariosDialog {
        id: scenarios
        controller: root.controller
        i18n: root.i18n
    }
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
                Components.PixelButton {
                    objectName: "intradayOpenScenariosButton"
                    text: root.i18n.catalog["quant.execution_scenarios"]
                    enabled: root.controller.dataLoaded
                    onClicked: scenarios.prepare(settings.values(), root.controller.scenarioPlan, root.controller.restoreRevision)
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
                        "quant.risk_folds", "quant.parameter_grid"].map(key => root.i18n.catalog[key])
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
                    if (view.selectedView >= 11) return root.i18n.catalog["risk." + value] || root.i18n.catalog["performance." + value] || value
                    return view.selectedView >= 7 ? (root.i18n.catalog["performance." + value] || value) : value
                }
                onPreviousRequested: root.controller.changePage(-1)
                onNextRequested: root.controller.changePage(1)
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
