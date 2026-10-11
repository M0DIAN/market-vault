import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradayFinalPanel"
    required property var controller
    required property var i18n
    property int bindingRevision: -1
    readonly property string sourceOverrideKey: controller.hasJointSelection ? "final.joint_source_override"
        : controller.hasThresholdSelection ? "final.threshold_source_override" : "quant.intraday_source_override"

    function sync() {
        if (bindingRevision !== controller.bindingRevision) {
            bindingRevision = controller.bindingRevision
            sourcePath.text = ""
            dataPath.text = ""
        }
        candidate.currentIndex = controller.researchController.candidateIndex
        view.selectedView = controller.viewIndex
        view.currentIndex = controller.viewIndex
        thresholdAccount.currentIndex = controller.thresholdAccountIndex
        equity.requestPaint()
    }
    Component.onCompleted: sync()
    Connections { target: root.controller; function onChanged() { root.sync() } }

    FileDialog {
        id: openSelection
        objectName: "intradaySelectionOpenDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        title: root.i18n.catalog["quant.intraday_selection_open"]
        onAccepted: root.controller.openSelection(selectedFile.toString())
    }
    FileDialog {
        id: saveSelection
        objectName: "intradaySelectionSaveDialog"
        fileMode: FileDialog.SaveFile
        nameFilters: ["JSON files (*.json)"]
        defaultSuffix: "json"
        title: root.i18n.catalog["quant.intraday_selection_save"]
        onAccepted: root.controller.saveSelection(selectedFile.toString())
    }
    FileDialog {
        id: openTest
        objectName: "intradayTestOpenDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        title: root.i18n.catalog["quant.intraday_test_open"]
        onAccepted: root.controller.openTest(selectedFile.toString())
    }
    FileDialog {
        id: saveTest
        objectName: "intradayTestSaveDialog"
        fileMode: FileDialog.SaveFile
        nameFilters: ["JSON files (*.json)"]
        defaultSuffix: "json"
        title: root.i18n.catalog["quant.intraday_test_save"]
        onAccepted: root.controller.saveTest(selectedFile.toString())
    }
    FileDialog {
        id: openInnerSource
        objectName: "intradayFinalInnerSourceDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        title: root.i18n.catalog["inner.open"]
        onAccepted: root.controller.openInnerSource(selectedFile.toString())
    }
    FileDialog {
        id: openThresholdSource
        objectName: "intradayFinalThresholdSourceDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        title: root.i18n.catalog["threshold.open"]
        onAccepted: root.controller.openThresholdSource(selectedFile.toString())
    }
    FileDialog {
        id: openJointSource
        objectName: "intradayFinalJointSourceDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        title: root.i18n.catalog["joint.open"]
        onAccepted: root.controller.openJointSource(selectedFile.toString())
    }
    FileDialog {
        id: sourcePicker
        objectName: "intradayFinalSourceDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        title: root.i18n.catalog[root.sourceOverrideKey]
        onAccepted: sourcePath.text = selectedFile.toString()
    }
    FileDialog {
        id: dataPicker
        objectName: "intradayFinalDataDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        title: root.i18n.catalog["quant.intraday_data_override"]
        onAccepted: dataPath.text = selectedFile.toString()
    }
    Dialog {
        id: locations
        objectName: "intradayFinalLocations"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(680, parent.width - 40)
        modal: true
        title: root.i18n.catalog["quant.intraday_locations"]
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ColumnLayout {
            spacing: Theme.PixelTheme.spacingSm
            Label { Layout.fillWidth: true; text: root.i18n.catalog[root.controller.hasJointSelection ? "final.joint_locations_help"
                : root.controller.hasThresholdSelection ? "final.threshold_locations_help" : "quant.intraday_locations_help"]; wrapMode: Text.WordWrap; color: Theme.PixelTheme.ink }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField { id: sourcePath; objectName: "intradayFinalSourcePath"; Layout.fillWidth: true; Layout.maximumWidth: Infinity; label: root.i18n.catalog[root.sourceOverrideKey]; onTextChanged: root.controller.setLocations(text, dataPath.text) }
                Components.PixelButton { objectName: "intradayFinalSourceBrowse"; text: root.i18n.catalog["quant.browse"]; onClicked: sourcePicker.open() }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField { id: dataPath; objectName: "intradayFinalDataPath"; Layout.fillWidth: true; Layout.maximumWidth: Infinity; label: root.i18n.catalog["quant.intraday_data_override"]; onTextChanged: root.controller.setLocations(sourcePath.text, text) }
                Components.PixelButton { objectName: "intradayFinalDataBrowse"; text: root.i18n.catalog["quant.browse"]; onClicked: dataPicker.open() }
            }
            RowLayout {
                Components.PixelButton { objectName: "intradayFinalLocationsClear"; text: root.i18n.catalog["quant.intraday_locations_clear"]; onClicked: { sourcePath.text = ""; dataPath.text = "" } }
                Item { Layout.fillWidth: true }
                Components.PixelButton { objectName: "intradayFinalLocationsDone"; text: root.i18n.catalog["quant.intraday_apply_settings"]; onClicked: locations.close() }
            }
        }
    }
    Dialog {
        id: details
        objectName: "intradayFinalDetailsDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(880, parent.width - 40)
        height: Math.min(650, parent.height - 40)
        modal: true
        title: root.i18n.catalog["quant.intraday_final_details"]
        standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            id: detailScroll
            objectName: "intradayFinalDetailsScroll"
            clip: true
            contentWidth: availableWidth
            rightPadding: detailsBar.width
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical: Components.PixelScrollBar {
                id: detailsBar
                objectName: "intradayFinalDetailsScrollBar"
                parent: detailScroll
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: parent.right
            }
            TextArea {
                objectName: "intradayFinalEvidenceText"
                width: detailScroll.availableWidth
                readOnly: true
                selectByMouse: true
                text: {
                    if (!details.visible) return ""
                    root.i18n.language
                    const values = root.controller.selectionEvidence
                    const lines = [root.controller.selectionDetails]
                    for (const key of Object.keys(values)) {
                        if (key === "method") continue
                        lines.push((root.i18n.catalog["final." + key] || root.i18n.catalog["inner." + key] || key) + ": " + values[key])
                    }
                    return lines.join("\n")
                }
                wrapMode: TextEdit.WrapAnywhere
                color: Theme.PixelTheme.ink
            }
        }
    }
    Dialog {
        id: pageEvidence
        objectName: "intradayFinalPageEvidenceDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(900, parent.width - 40)
        height: Math.min(650, parent.height - 40)
        modal: true
        title: root.i18n.catalog["threshold.page_evidence"]
        standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            objectName: "intradayFinalPageEvidenceScroll"
            clip: true
            contentWidth: availableWidth
            TextArea {
                objectName: "intradayFinalPageEvidenceText"
                width: parent.width
                readOnly: true
                selectByMouse: true
                text: pageEvidence.visible ? root.controller.currentPageEvidence : ""
                wrapMode: TextEdit.WrapAnywhere
                color: Theme.PixelTheme.ink
            }
        }
    }

    ScrollView {
        id: scroll
        objectName: "intradayFinalScroll"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        rightPadding: verticalBar.width
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {
            id: verticalBar
            objectName: "intradayFinalScrollBar"
            parent: scroll
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
        }

        ColumnLayout {
            width: scroll.availableWidth
            height: Math.max(implicitHeight, scroll.availableHeight)
            spacing: Theme.PixelTheme.spacingSm

            RowLayout {
                Layout.fillWidth: true
                enabled: !root.controller.busy && !operationRuntime.busy
                Components.LabeledComboBox {
                    id: candidate
                    objectName: "intradayFinalCandidate"
                    Layout.fillWidth: true
                    Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.intraday_development_candidate"]
                    model: root.controller.researchController.candidateNames
                    onSelected: root.controller.researchController.selectCandidate(currentIndex)
                }
                Components.PixelButton {
                    objectName: "intradayFreezeButton"
                    text: root.i18n.catalog["quant.intraday_freeze"]
                    enabled: root.controller.canFreeze
                    onClicked: root.controller.freezeSelected()
                }
                Components.PixelStatusBadge { status: root.controller.status; text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) } }
            }
            RowLayout {
                Layout.fillWidth: true
                enabled: !root.controller.busy && !operationRuntime.busy
                Components.PixelButton { objectName: "intradayFinalInnerOpenButton"; text: root.i18n.catalog["inner.open"]; onClicked: openInnerSource.open() }
                Label {
                    objectName: "intradayFinalInnerSource"
                    Layout.fillWidth: true
                    text: root.controller.innerSourceDetails || root.i18n.catalog["quant.intraday_inner_freeze_help"]
                    elide: Text.ElideMiddle
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                    ToolTip.visible: innerHover.hovered
                    ToolTip.text: text
                    HoverHandler { id: innerHover }
                }
                Components.PixelButton { objectName: "intradayFreezeInnerButton"; text: root.i18n.catalog["quant.intraday_freeze_inner"]; enabled: root.controller.canFreezeInner; onClicked: root.controller.freezeInnerSelection() }
            }
            RowLayout {
                Layout.fillWidth: true
                enabled: !root.controller.busy && !operationRuntime.busy
                Components.PixelButton { objectName: "intradayFinalThresholdOpenButton"; text: root.i18n.catalog["threshold.open"]; onClicked: openThresholdSource.open() }
                Label {
                    objectName: "intradayFinalThresholdSource"
                    Layout.fillWidth: true
                    text: root.controller.thresholdSourceDetails || root.i18n.catalog["final.threshold_freeze_help"]
                    elide: Text.ElideMiddle
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                    ToolTip.visible: thresholdHover.hovered
                    ToolTip.text: text
                    HoverHandler { id: thresholdHover }
                }
                Components.PixelButton { objectName: "intradayFreezeThresholdButton"; text: root.i18n.catalog["final.freeze_threshold"]; enabled: root.controller.canFreezeThreshold; onClicked: root.controller.freezeThresholdSelection() }
            }
            RowLayout {
                Layout.fillWidth: true
                enabled: !root.controller.busy && !operationRuntime.busy
                Components.PixelButton { objectName: "intradayFinalJointOpenButton"; text: root.i18n.catalog["joint.open"]; onClicked: openJointSource.open() }
                Label {
                    objectName: "intradayFinalJointSource"
                    Layout.fillWidth: true
                    text: root.controller.jointSourceDetails || root.i18n.catalog["final.joint_freeze_help"]
                    elide: Text.ElideMiddle
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                    ToolTip.visible: jointHover.hovered
                    ToolTip.text: text
                    HoverHandler { id: jointHover }
                }
                Components.PixelButton { objectName: "intradayFreezeJointButton"; text: root.i18n.catalog["final.freeze_joint"]; enabled: root.controller.canFreezeJoint; onClicked: root.controller.freezeJointSelection() }
            }
            Label {
                Layout.fillWidth: true
                text: root.i18n.catalog["quant.intraday_final_help"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradayFreezeUnsupported"
                Layout.fillWidth: true
                visible: root.controller.freezeUnsupported
                text: root.i18n.catalog["quant.intraday_freeze_unsupported"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
            }
            RowLayout {
                Layout.fillWidth: true
                enabled: !root.controller.busy && !operationRuntime.busy
                Components.PixelButton { objectName: "intradaySelectionOpenButton"; text: root.i18n.catalog["quant.intraday_selection_open"]; onClicked: openSelection.open() }
                Components.PixelButton { objectName: "intradaySelectionSaveButton"; text: root.i18n.catalog["quant.intraday_selection_save"]; enabled: root.controller.selectionLoaded; onClicked: saveSelection.open() }
                Components.PixelButton { objectName: "intradaySelectionReplayButton"; text: root.i18n.catalog["quant.intraday_selection_replay"]; enabled: root.controller.selectionLoaded; onClicked: root.controller.replaySelection(sourcePath.text, dataPath.text) }
                Components.PixelButton { objectName: "intradayRunTestButton"; text: root.i18n.catalog["quant.intraday_test_run"]; variant: "primary"; enabled: root.controller.selectionLoaded; onClicked: root.controller.runTest(sourcePath.text, dataPath.text) }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.PixelButton { objectName: "intradayTestOpenButton"; text: root.i18n.catalog["quant.intraday_test_open"]; enabled: !operationRuntime.busy; onClicked: openTest.open() }
                Components.PixelButton { objectName: "intradayTestSaveButton"; text: root.i18n.catalog["quant.intraday_test_save"]; enabled: root.controller.testLoaded && !operationRuntime.busy; onClicked: saveTest.open() }
                Components.PixelButton { objectName: "intradayTestReplayButton"; text: root.i18n.catalog["quant.intraday_test_replay"]; enabled: root.controller.testLoaded && !operationRuntime.busy; onClicked: root.controller.replayTest(sourcePath.text, dataPath.text) }
                Components.PixelButton { objectName: "intradayFinalLocationsButton"; text: root.i18n.catalog["quant.intraday_locations"]; enabled: root.controller.selectionLoaded; onClicked: locations.open() }
            }
            Label {
                Layout.fillWidth: true
                visible: text.length > 0
                text: root.controller.error || root.i18n.catalog["inner." + root.controller.notice] || ((sourcePath.text || dataPath.text) ? root.i18n.catalog["quant.intraday_locations_active"] : "")
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.SummaryStrip {
                Layout.fillWidth: true
                i18n: root.i18n
                summary: {
                    const result = root.controller.resultSummary
                    const keys = {FROZEN: "quant.intraday_frozen", COMPUTED: "quant.intraday_computed", RECORDED: "quant.snapshot_loaded",
                        REPLAY_MATCH: "quant.replay_verified", REPLAY_PENDING: "quant.intraday_replay_pending", REPLAY_FAILED: "quant.intraday_replay_failed",
                        REPLAY_STALE_INPUT: "final.replay_stale"}
                    for (const key of ["intraday_selection_proof", "intraday_test_proof"]) {
                        if (result[key]) result[key] = root.i18n.catalog[keys[result[key]]]
                    }
                    return result
                }
            }
            Label {
                objectName: "intradayFinalCompletedPaths"
                Layout.fillWidth: true
                visible: root.controller.selectionPath.length > 0 || root.controller.testPath.length > 0
                text: (root.controller.selectionPath ? root.i18n.catalog["final.saved_selection_path"] + ": " + root.controller.selectionPath : "")
                    + (root.controller.testPath ? "\n" + root.i18n.catalog["final.saved_test_path"] + ": " + root.controller.testPath : "")
                wrapMode: Text.WrapAnywhere
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradaySelectionDetails"
                Layout.fillWidth: true
                visible: root.controller.selectionLoaded
                text: root.controller.selectionDetails
                elide: Text.ElideMiddle
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
                ToolTip.visible: detailsHover.hovered
                ToolTip.text: root.controller.selectionDetails + "\n" + root.controller.provenanceDetails
                HoverHandler { id: detailsHover }
            }
            Components.PixelButton {
                objectName: "intradayFinalDetailsButton"
                text: root.i18n.catalog["quant.intraday_final_details"]
                enabled: root.controller.selectionLoaded
                onClicked: details.open()
            }
            Label {
                objectName: "intradayFinalMethod"
                Layout.fillWidth: true
                property bool quadraticModel: root.controller.selectionLoaded && view.selectedView === 4
                    && root.controller.frozenCandidate.strategy.kind === "QUADRATIC_RIDGE"
                visible: root.controller.hasDevSelection || quadraticModel
                text: (root.controller.hasDevSelection ? root.i18n.catalog[root.controller.hasJointSelection ? "final.joint_method"
                    : root.controller.hasThresholdSelection ? "final.threshold_method" : "quant.intraday_final_selection_method"] : "")
                    + (quadraticModel ? "\n" + root.i18n.catalog["quant.intraday_final_model_help"] : "")
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradayFinalReturnBasis"
                Layout.fillWidth: true
                visible: root.controller.hasEconomicSelection
                text: root.controller.returnBasis.price_basis ? root.i18n.catalog["quant.return_basis_help"] : ""
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.LabeledComboBox {
                id: view
                objectName: "intradayTestView"
                Layout.fillWidth: true
                Layout.maximumWidth: 350
                visible: root.controller.selectionLoaded
                label: root.i18n.catalog["quant.intraday_result_view"]
                property int selectedView: 0
                model: ["quant.intraday_overview", "quant.trades", "quant.intraday_ledger", "quant.intraday_daily",
                    "quant.intraday_final_model", "quant.intraday_predictions", "quant.performance",
                    "quant.performance_exit", "quant.performance_entry", "quant.performance_day",
                    "quant.risk_summary", "quant.risk_drawdowns", "quant.risk_distributions", "quant.risk_concentration",
                    "quant.risk_folds"].concat(root.controller.hasEconomicSelection ? [root.controller.hasJointSelection ? "final.joint_family" : "final.threshold_family",
                    root.controller.hasJointSelection ? "final.joint_models" : "final.threshold_model", "final.keys", "final.threshold_decisions",
                    "final.threshold_trades", "final.threshold_daily", "final.threshold_ledger", "final.threshold_transactions", "threshold.sessions", "threshold.prices"]
                    : root.controller.hasDevSelection ? ["final.family", "final.models", "final.keys", "final.predictions"] : []).map(key => root.i18n.catalog[key])
                onSelected: { selectedView = currentIndex; root.controller.selectView(currentIndex) }
                onModelChanged: { selectedView = root.controller.viewIndex < model.length ? root.controller.viewIndex : 0; currentIndex = selectedView }
            }
            Components.LabeledComboBox {
                id: thresholdAccount
                objectName: "intradayFinalThresholdAccount"
                Layout.fillWidth: true
                Layout.maximumWidth: root.controller.hasJointSelection ? 600 : 350
                visible: root.controller.hasEconomicSelection && view.selectedView >= 15
                label: root.i18n.catalog[root.controller.hasJointSelection ? "final.joint_account" : "final.threshold_account"]
                model: root.controller.thresholdAccountOptions.map(option => (root.controller.hasJointSelection
                    ? root.i18n.catalog["prediction_quality." + option.strategy_kind] + " · alpha=" + option.alpha + " · " : "")
                    + option.threshold_bps + " bp" + (option.chosen ? " · " + root.i18n.catalog["threshold.chosen"] : ""))
                onSelected: root.controller.selectThresholdAccount(currentIndex)
                onModelChanged: currentIndex = root.controller.thresholdAccountIndex
            }
            Label {
                objectName: "intradayFinalThresholdDecisionNote"
                Layout.fillWidth: true
                visible: root.controller.hasEconomicSelection && view.selectedView >= 15
                text: root.i18n.catalog[root.controller.hasJointSelection ? "final.joint_decision_note" : "final.threshold_decision_note"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.PixelButton {
                objectName: "intradayFinalPageEvidenceButton"
                text: root.i18n.catalog["threshold.page_evidence"]
                enabled: root.controller.selectionLoaded
                onClicked: pageEvidence.open()
            }
            ColumnLayout {
                visible: root.controller.testLoaded && view.selectedView === 0
                Layout.fillWidth: true
                spacing: 2
                Label { text: root.i18n.catalog["quant.intraday_equity_legend"]; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm }
                Canvas {
                    id: equity
                    objectName: "intradayTestEquity"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 64
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
                objectName: "intradayTestTable"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: root.controller.hasEconomicSelection && view.selectedView === 15 ? 220
                    : view.selectedView === 0 ? 120 : 170
                paged: true
                tableModel: root.controller.tableModel
                i18n: root.i18n
                cellFormatter: function(value) {
                    root.i18n.language
                    const prefixes = view.selectedView >= 15 || view.selectedView === 4
                        ? ["threshold.", "inner.", "performance."]
                        : view.selectedView >= 10 ? ["risk.", "performance."]
                        : view.selectedView >= 6 ? ["performance."] : []
                    if (root.controller.hasJointSelection && (view.selectedView >= 15 || view.selectedView === 4))
                        prefixes.push("prediction_quality.")
                    for (const prefix of prefixes) {
                        const key = prefix + value, translated = root.i18n.translate(key)
                        if (translated && translated !== key) return translated
                    }
                    return value
                }
                onPreviousRequested: root.controller.changePage(-1)
                onNextRequested: root.controller.changePage(1)
            }
            Label {
                Layout.fillWidth: true
                visible: root.controller.testLoaded && view.selectedView >= 6 && view.selectedView <= 14
                text: {
                    if (view.selectedView < 10) return root.i18n.catalog["quant.performance_note"]
                    const note = ["", "quant.risk_drawdowns_note", "quant.risk_distributions_note",
                        "quant.risk_concentration_note", "quant.risk_folds_note"][view.selectedView - 10]
                    return root.i18n.catalog["quant.risk_note"] + (note ? "\n" + root.i18n.catalog[note] : "")
                }
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
        }
    }
}
