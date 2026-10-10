import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradayThresholdPanel"
    required property var controller
    required property var i18n
    function label(key) {
        return root.i18n.catalog["threshold." + key] || root.i18n.catalog["history." + key]
            || root.i18n.catalog["inner." + key] || key
    }
    function scopeLabel(value) {
        return root.label(value.kind) + (value.kind === "OUTER_INNER" ? " " + value.fold_index : "")
    }
    function accountLabel(value) {
        return value.kind === "THRESHOLD" ? value.threshold_bps + " bp" + (value.chosen ? " · " + root.label("chosen") : "")
            : root.label(value.kind)
    }
    function sync() {
        candidate.currentIndex = controller.researchController.candidateIndex
        equity.requestPaint()
    }
    Component.onCompleted: sync()
    Connections { target: root.controller; function onChanged() { root.sync() } }
    FileDialog {
        id: openFile; objectName: "intradayThresholdOpenDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        title: root.label("open")
        onAccepted: root.controller.openExperiment(selectedFile.toString())
    }
    FileDialog {
        id: saveFile; objectName: "intradayThresholdSaveDialog"
        fileMode: FileDialog.SaveFile; nameFilters: ["JSON files (*.json)"]; defaultSuffix: "json"
        title: root.label("save")
        onAccepted: root.controller.saveExperiment(selectedFile.toString())
    }
    FileDialog {
        id: dataFile; objectName: "intradayThresholdDataDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.setDataLocator(selectedFile.toString())
    }
    FileDialog {
        id: sourceFile; objectName: "intradayThresholdSourceDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.setSourceLocator(selectedFile.toString())
    }
    Dialog {
        id: details; objectName: "intradayThresholdDetailsDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(900, parent.width - 40); height: Math.min(650, parent.height - 40)
        modal: true; title: root.label("details"); standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            clip: true; contentWidth: availableWidth
            TextArea {
                objectName: "intradayThresholdDetailsText"
                width: parent.width; readOnly: true; selectByMouse: true
                text: details.visible ? root.controller.completedDetails : ""
                wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
            }
        }
    }
    Dialog {
        id: evidence; objectName: "intradayThresholdEvidenceDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(900, parent.width - 40); height: Math.min(650, parent.height - 40)
        modal: true; title: root.label("page_evidence"); standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            objectName: "intradayThresholdEvidenceScroll"
            clip: true; contentWidth: availableWidth
            TextArea {
                objectName: "intradayThresholdEvidenceText"
                width: parent.width; readOnly: true; selectByMouse: true
                text: evidence.visible ? root.controller.currentPageEvidence : ""
                wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
            }
        }
    }
    ScrollView {
        id: scroll; objectName: "intradayThresholdScroll"
        anchors.fill: parent; clip: true; contentWidth: availableWidth
        rightPadding: verticalBar.width
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {
            id: verticalBar; objectName: "intradayThresholdScrollBar"
            parent: scroll
            anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right
        }
        ColumnLayout {
            width: scroll.availableWidth; height: Math.max(implicitHeight, scroll.availableHeight)
            spacing: Theme.PixelTheme.spacingSm
            Label {
                objectName: "intradayThresholdMethod"
                Layout.fillWidth: true; text: root.label("method")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledComboBox {
                    id: candidate; objectName: "intradayThresholdCandidate"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("source"); model: root.controller.researchController.candidateNames
                    onSelected: root.controller.researchController.selectCandidate(currentIndex)
                    onModelChanged: currentIndex = root.controller.researchController.candidateIndex
                }
                Components.PixelButton {
                    objectName: "intradayThresholdRunButton"; text: root.label("run")
                    enabled: root.controller.canRun && !operationRuntime.busy
                    onClicked: root.controller.runSelected()
                }
            }
            Label {
                objectName: "intradayThresholdSource"
                Layout.fillWidth: true
                text: {
                    root.i18n.language
                    const source = root.controller.draftSource
                    if (!root.controller.canRun) return root.label("source_required")
                    return root.label("current_source") + ": " + source.source_path + " · "
                        + root.label("cost_index") + " " + source.cost_index + " · "
                        + root.label("candidate_index") + " " + source.candidate_index
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    id: dataPath; objectName: "intradayThresholdDataPath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("data"); text: root.controller.dataLocator
                    onTextChanged: root.controller.setDataLocator(text)
                }
                Components.PixelButton {
                    objectName: "intradayThresholdDataBrowse"; text: root.i18n.catalog["quant.browse"]
                    onClicked: dataFile.open()
                }
                Components.PixelButton {
                    objectName: "intradayThresholdDataClear"; text: root.label("clear")
                    onClicked: root.controller.setDataLocator("")
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    id: sourcePath; objectName: "intradayThresholdSourcePath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("replay_source"); text: root.controller.sourceLocator
                    onTextChanged: root.controller.setSourceLocator(text)
                }
                Components.PixelButton {
                    objectName: "intradayThresholdSourceBrowse"; text: root.i18n.catalog["quant.browse"]
                    onClicked: sourceFile.open()
                }
                Components.PixelButton {
                    objectName: "intradayThresholdSourceClear"; text: root.label("clear")
                    onClicked: root.controller.setSourceLocator("")
                }
            }
            Flow {
                Layout.fillWidth: true; spacing: Theme.PixelTheme.spacingSm
                Components.PixelButton {
                    objectName: "intradayThresholdOpenButton"; text: root.label("open")
                    enabled: !operationRuntime.busy; onClicked: openFile.open()
                }
                Components.PixelButton {
                    objectName: "intradayThresholdSaveButton"; text: root.label("save")
                    enabled: root.controller.resultLoaded && !operationRuntime.busy; onClicked: saveFile.open()
                }
                Components.PixelButton {
                    objectName: "intradayThresholdReplayButton"; text: root.label("replay")
                    enabled: root.controller.resultLoaded && !operationRuntime.busy; onClicked: root.controller.replayExperiment()
                }
                Components.PixelButton {
                    objectName: "intradayThresholdDetailsButton"; text: root.label("details")
                    enabled: root.controller.resultLoaded; onClicked: details.open()
                }
            }
            Label {
                objectName: "intradayThresholdSummary"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: {
                    root.i18n.language
                    const result = root.controller.resultSummary
                    if (!result.status) return ""
                    const recipe = result.final_recipe
                    return root.label(result.status) + " · " + root.label(root.controller.proof)
                        + " · " + result.strategy.kind + " · alpha=" + result.strategy.alpha
                        + " · " + root.label("folds") + ": " + result.fold_count + " · " + root.label("days") + ": " + result.day_count
                        + "\n" + root.label("final_threshold") + ": " + (recipe ? recipe.threshold * 10000 + " bp" : root.label("not_computed"))
                }
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.ink
            }
            Label {
                objectName: "intradayThresholdNotice"
                Layout.fillWidth: true
                visible: root.controller.draftChanged || root.controller.notice.length > 0 || root.controller.studyError.length > 0
                text: root.controller.studyError ? root.controller.studyError + "\n" + root.label("retry")
                    : root.controller.notice ? root.label(root.controller.notice) : root.label("draft_changed")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            Label {
                objectName: "intradayThresholdUnavailable"
                Layout.fillWidth: true; visible: root.controller.resultSummary.status === "UNAVAILABLE"
                text: root.label("WHOLE_STUDY_NOT_COMPUTED") + "\n" + (root.controller.resultSummary.unavailable_reasons || []).map(row =>
                    root.label(row.scope) + (typeof row.fold_index === "number" ? " " + row.fold_index : "") + ": " + root.label(row.reason)).join("\n")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledComboBox {
                    id: scope; objectName: "intradayThresholdScope"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("scope")
                    model: root.controller.scopeOptions.map(value => root.scopeLabel(value))
                    currentIndex: root.controller.scopeIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.scopeIndex)
                    onSelected: root.controller.selectScope(currentIndex)
                }
                Components.LabeledComboBox {
                    id: account; objectName: "intradayThresholdAccount"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("account")
                    model: root.controller.accountOptions.map(value => root.accountLabel(value))
                    currentIndex: root.controller.accountIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.accountIndex)
                    onSelected: root.controller.selectAccount(currentIndex)
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledComboBox {
                    id: view; objectName: "intradayThresholdView"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.intraday_result_view"]
                    model: ["overview", "keys", "models", "decisions", "trades", "daily", "ledger", "transactions",
                        "fold_contributions", "sessions", "prices"].map(key => root.label(key))
                    currentIndex: root.controller.viewIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.viewIndex)
                    onSelected: root.controller.selectView(currentIndex)
                }
                Components.PixelButton {
                    objectName: "intradayThresholdEvidenceButton"; text: root.label("page_evidence")
                    enabled: root.controller.resultLoaded; onClicked: evidence.open()
                }
            }
            Label {
                objectName: "intradayThresholdScopeSummary"
                Layout.fillWidth: true; visible: root.controller.resultLoaded && root.controller.scopeIndex > 0
                text: {
                    root.i18n.language
                    const result = root.controller.scopeSummary
                    if (!result.training_boundary) return ""
                    return root.label("training_boundary") + ": " + result.training_boundary
                        + "\n" + root.label("history_boundary") + ": " + result.history_boundary
                        + " · TRAIN: " + result.training_count + " · READY: " + result.prediction_count
                        + (result.execution_input.detail ? "\n" + root.label(result.execution_input.reason) + ": " + result.execution_input.detail : "")
                }
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradayThresholdViewNotice"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: root.label(root.controller.viewNotice)
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradayThresholdReturnBasis"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: {
                    root.i18n.language
                    const basis = root.controller.returnBasis
                    return Object.keys(basis).map(key => root.label(key) + ": " + root.label(basis[key])).join(" · ")
                }
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                Layout.fillWidth: true; visible: root.controller.viewIndex === 0 && root.controller.resultLoaded
                text: root.label("economic_note") + "\n" + root.controller.equityOptions.map((value, index) =>
                    root.accountLabel(value) + " (" + root.label(["gold", "blue", "green", "grey"][index]) + ")").join(" · ")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Canvas {
                id: equity; objectName: "intradayThresholdEquity"
                Layout.fillWidth: true; Layout.preferredHeight: 54
                visible: root.controller.viewIndex === 0 && root.controller.equitySeries.length > 0
                onWidthChanged: requestPaint()
                onPaint: {
                    const ctx = getContext("2d"), series = root.controller.equitySeries
                    ctx.clearRect(0, 0, width, height)
                    if (!series.length) return
                    const points = [].concat(...series)
                    let xmin = points[0][0], xmax = xmin, ymin = 1, ymax = 1
                    points.forEach(p => { xmin = Math.min(xmin, p[0]); xmax = Math.max(xmax, p[0]); ymin = Math.min(ymin, p[1]); ymax = Math.max(ymax, p[1]) })
                    const dx = xmax - xmin || 1, dy = ymax - ymin || .01
                    ctx.fillStyle = "#7a756a"; ctx.font = "10px sans-serif"
                    ctx.fillText(ymax.toFixed(3), 0, 12); ctx.fillText(ymin.toFixed(3), 0, height - 3)
                    series.forEach((values, index) => {
                        ctx.strokeStyle = ["#9a7427", "#4a8294", "#53826a", "#82756d"][index]; ctx.lineWidth = 2; ctx.beginPath()
                        values.forEach((p, i) => { const x = 42 + (p[0] - xmin) / dx * (width - 50), y = height - 8 - (p[1] - ymin) / dy * (height - 16); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y) })
                        ctx.stroke()
                    })
                }
            }
            Components.DataTable {
                objectName: "intradayThresholdTable"
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 220; Layout.preferredHeight: 260
                paged: true; tableModel: root.controller.tableModel; i18n: root.i18n
                cellFormatter: function(value) {
                    return root.i18n.catalog["threshold." + value] || root.i18n.catalog["history." + value]
                        || root.i18n.catalog["inner." + value] || root.i18n.catalog["performance." + value]
                        || root.i18n.catalog["risk." + value] || root.i18n.catalog["prediction_quality." + value]
                        || root.i18n.catalog["comparison." + value] || root.i18n.catalog["columns." + value] || value
                }
                onPreviousRequested: root.controller.changePage(-1)
                onNextRequested: root.controller.changePage(1)
            }
        }
    }
}
