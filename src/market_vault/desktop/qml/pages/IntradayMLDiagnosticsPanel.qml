import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradayMLDiagnosticsPanel"
    required property var controller
    required property var i18n
    function label(key) { return root.i18n.catalog["ml_diagnostics." + key] || root.i18n.catalog["uncertainty." + key] || root.i18n.catalog["prediction_quality." + key] || root.i18n.catalog["inner." + key] || key }
    FileDialog {
        id: sourceFile; objectName: "intradayMLSourceDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.openSource(selectedFile.toString())
    }
    FileDialog {
        id: dataFile; objectName: "intradayMLDataDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.setDataLocator(selectedFile.toString())
    }
    Dialog {
        id: details; objectName: "intradayMLDetailsDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(900, parent.width - 40); height: Math.min(650, parent.height - 40)
        modal: true; title: root.label("details"); standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            objectName: "intradayMLDetailsScroll"
            clip: true; contentWidth: availableWidth
            TextArea {
                objectName: "intradayMLDetailsText"
                width: parent.width; readOnly: true; selectByMouse: true
                text: details.visible ? root.controller.completedDetails : ""
                wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
            }
        }
    }
    Dialog {
        id: evidence; objectName: "intradayMLEvidenceDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(900, parent.width - 40); height: Math.min(650, parent.height - 40)
        modal: true; title: root.label("page_evidence"); standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            objectName: "intradayMLEvidenceScroll"
            clip: true; contentWidth: availableWidth
            TextArea {
                objectName: "intradayMLEvidenceText"
                width: parent.width; readOnly: true; selectByMouse: true
                text: evidence.visible ? root.controller.currentPageEvidence : ""
                wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
            }
        }
    }
    ScrollView {
        id: scroll; objectName: "intradayMLScroll"
        anchors.fill: parent; clip: true; contentWidth: availableWidth
        rightPadding: verticalBar.width
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {
            id: verticalBar; objectName: "intradayMLScrollBar"
            parent: scroll
            anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right
        }
        ColumnLayout {
            width: scroll.availableWidth; height: Math.max(implicitHeight, scroll.availableHeight)
            spacing: Theme.PixelTheme.spacingSm
            Components.LabeledComboBox {
                objectName: "intradayMLMode"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity
                label: root.label("mode")
                model: ["quality_mode", "sensitivity_mode", "uncertainty_mode"].map(key => root.label(key))
                currentIndex: root.controller.modeIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.modeIndex)
                onSelected: root.controller.selectMode(currentIndex)
            }
            Label {
                objectName: "intradayMLMethod"
                Layout.fillWidth: true
                text: root.label(root.controller.uncertaintyMode ? "uncertainty_method" : root.controller.sensitivityMode ? "sensitivity_method" : "method")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    objectName: "intradayMLSourcePath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("source"); text: root.controller.sourcePath
                    onTextChanged: root.controller.setSourcePath(text)
                }
                Components.PixelButton {
                    objectName: "intradayMLSourceBrowse"; text: root.i18n.catalog["quant.browse"]
                    enabled: !operationRuntime.busy; onClicked: sourceFile.open()
                }
                Components.PixelButton {
                    objectName: "intradayMLOpenButton"; text: root.label("open")
                    enabled: !operationRuntime.busy; onClicked: root.controller.openSource(root.controller.sourcePath)
                }
            }
            Label {
                objectName: "intradayMLDraftSource"
                Layout.fillWidth: true
                text: {
                    root.i18n.language
                    const source = root.controller.draftSource
                    return source.experiment_id ? root.label(source.source_kind) + " · " + source.name + "\n" + source.experiment_id : root.label("source_required")
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.inkMuted
            }
            RowLayout {
                Layout.fillWidth: true; visible: root.controller.ordinarySource && !root.controller.recordedOnlyMode
                Components.LabeledComboBox {
                    objectName: "intradayMLCost"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("cost"); model: root.controller.costNames
                    currentIndex: root.controller.costIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.costIndex)
                    onSelected: root.controller.selectCost(currentIndex)
                }
                Components.LabeledComboBox {
                    objectName: "intradayMLCandidate"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("candidate"); model: root.controller.candidateNames
                    currentIndex: root.controller.candidateIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.candidateIndex)
                    onSelected: root.controller.selectCandidate(currentIndex)
                }
            }
            RowLayout {
                objectName: "intradayMLDataRow"
                Layout.fillWidth: true; visible: !root.controller.recordedOnlyMode
                Components.LabeledTextField {
                    objectName: "intradayMLDataPath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("data"); text: root.controller.dataLocator
                    onTextChanged: root.controller.setDataLocator(text)
                }
                Components.PixelButton {
                    objectName: "intradayMLDataBrowse"; text: root.i18n.catalog["quant.browse"]
                    onClicked: dataFile.open()
                }
                Components.PixelButton {
                    objectName: "intradayMLDataClear"; text: root.label("clear")
                    onClicked: root.controller.setDataLocator("")
                }
            }
            Flow {
                Layout.fillWidth: true; spacing: Theme.PixelTheme.spacingSm
                Components.PixelButton {
                    objectName: "intradayMLRunButton"; text: root.label("run")
                    enabled: root.controller.canRun && !operationRuntime.busy
                    onClicked: root.controller.runSelected()
                }
                Components.PixelButton {
                    objectName: "intradayMLDetailsButton"; text: root.label("details")
                    enabled: root.controller.resultLoaded; onClicked: details.open()
                }
            }
            Label {
                objectName: "intradayMLSummary"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: {
                    root.i18n.language
                    const result = root.controller.resultSummary, sample = result.sample, sampling = result.sampling
                    if (!result.status) return ""
                    return root.label(result.diagnostic_kind) + " · " + root.label(result.status) + " · " + root.label(result.source_kind)
                        + (sample && root.controller.completedUncertainty ? "\n" + root.label("days") + ": " + sample.sample_count
                        + " · " + root.label("folds") + ": " + sample.fold_count + " · " + sample.first_day + " – " + sample.last_day
                        : sample && root.controller.completedSensitivity ? "\n" + root.label("outer_windows") + ": " + sample.outer_window_count
                        + " · " + root.label("final_windows") + ": " + sample.final_dev_window_count
                        + " · " + root.label("omissions") + ": " + sample.omission_count
                        : sample ? "\n" + root.label("folds") + ": " + (sample.fold_count || 0)
                        + " · " + root.label("days") + ": " + (sample.evaluated_day_count || 0)
                        + " · READY: " + (sample.prediction_count || 0) + " · COMPLETE: " + (sample.complete_target_count || 0)
                        + " · " + root.label("incomplete") + ": " + (sample.incomplete_target_count || 0) : "")
                        + (sampling && root.controller.completedUncertainty ? "\n" + root.label("replications") + ": " + sampling.replications
                        + " · " + root.label("seed") + ": " + sampling.seed + " · " + root.label("block_days") + ": " + sampling.block_days
                        + " · " + root.label(result.basis_matches ? "basis_matched" : "basis_mismatch") : "")
                        + "\n" + result.source_path
                        + (result.unavailable_reasons.length ? "\n" + JSON.stringify(result.unavailable_reasons) : "")
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.ink
            }
            Label {
                objectName: "intradayMLNotice"
                Layout.fillWidth: true
                visible: root.controller.draftChanged || root.controller.notice.length > 0 || root.controller.studyError.length > 0 || root.controller.draftNotice.length > 0
                text: root.controller.studyError ? root.controller.studyError + "\n" + root.label("retry")
                    : root.controller.notice ? root.label(root.controller.notice)
                    : root.controller.draftNotice ? root.label(root.controller.draftNotice) : root.label("draft_changed")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledComboBox {
                    objectName: "intradayMLScope"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label(root.controller.completedUncertainty ? "return_scope" : root.controller.completedSensitivity ? "inner_scope" : "scope")
                    model: root.controller.scopeOptions.map(option => root.label(option.kind) + (typeof option.fold_index === "number" ? " " + option.fold_index : ""))
                    currentIndex: root.controller.scopeIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.scopeIndex)
                    onSelected: root.controller.selectScope(currentIndex)
                }
                Components.LabeledComboBox {
                    objectName: "intradayMLView"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.intraday_result_view"]
                    model: root.controller.viewOptions.map(key => root.label(key))
                    currentIndex: root.controller.viewIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.viewIndex)
                    onSelected: root.controller.selectView(currentIndex)
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: root.controller.completedUncertainty && root.controller.viewIndex === 3
                Components.LabeledComboBox {
                    objectName: "intradayMLEvidenceAccount"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("evidence_account")
                    model: root.controller.evidenceAccountOptions.map(key => root.label(key))
                    currentIndex: root.controller.evidenceAccountIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.evidenceAccountIndex)
                    onSelected: root.controller.selectEvidenceAccount(currentIndex)
                }
                Components.LabeledComboBox {
                    objectName: "intradayMLEvidenceSection"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("evidence_section")
                    model: root.controller.evidenceSectionOptions.map(key => root.i18n.catalog["ml_diagnostics.account_field." + key] || key)
                    currentIndex: root.controller.evidenceSectionIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.evidenceSectionIndex)
                    onSelected: root.controller.selectEvidenceSection(currentIndex)
                }
            }
            Components.PixelButton {
                objectName: "intradayMLEvidenceButton"; text: root.label("page_evidence")
                enabled: root.controller.resultLoaded; onClicked: evidence.open()
            }
            Label {
                objectName: "intradayMLInterpretation"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: root.controller.completedUncertainty ? root.label("return_interpretation") + "\n" + root.label("return_units")
                    : root.controller.completedSensitivity ? root.label("sensitivity_interpretation") + "\n"
                    + root.label(root.controller.resultSummary.source_kind === "ECONOMIC_THRESHOLD_SELECTION" ? "cash_objective" : "mse_objective")
                    : root.label("interpretation") + (root.controller.resultSummary.source_kind === "ECONOMIC_THRESHOLD_SELECTION" ? "\n" + root.label("same_scores") : "")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.DataTable {
                objectName: "intradayMLTable"
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 210
                paged: true; tableModel: root.controller.tableModel; i18n: root.i18n
                cellFormatter: function(value) {
                    root.i18n.language
                    const prefixes = root.controller.completedUncertainty
                        ? ["uncertainty.", "ml_diagnostics.", "prediction_quality.", "inner.", "columns."]
                        : ["ml_diagnostics.", "prediction_quality.", "inner.", "columns."]
                    for (const prefix of prefixes) {
                        const key = prefix + value
                        const translated = root.i18n.translate(key)
                        if (translated && translated !== key) return translated
                    }
                    return value
                }
                onPreviousRequested: root.controller.changePage(-1)
                onNextRequested: root.controller.changePage(1)
            }
        }
    }
}
