import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradayProcedureStressPanel"
    required property var controller
    required property var i18n
    // Language changes replace this catalog once; path edits never fetch it
    // for every cell of a completed account table.
    readonly property var catalog: i18n.catalog
    function label(key) {
        for (const prefix of ["procedure_stress.", "procedure.", "signal_delay.", "ml_diagnostics.", "uncertainty.", "inner.", "columns."])
            if (root.catalog[prefix + key]) return root.catalog[prefix + key]
        return key
    }
    function sourceText(source) {
        return source.experiment_id ? root.label(source.source_kind) + (source.name ? " · " + source.name : "")
            + "\n" + source.experiment_id + "\n" + source.path : root.label("not_opened")
    }
    function scenarioText(scenario) {
        return "#" + scenario.scenario_index + " · +" + scenario.additional_slippage_bps + " bp · "
            + root.label("delay") + " " + scenario.delay_bars + " " + root.label("planned_bars")
    }
    FileDialog {
        id: sourceFile; objectName: "intradayProcedureStressFileDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.setSourcePath(selectedFile.toString())
    }
    Dialog {
        id: report; objectName: "intradayProcedureStressReportDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(950, parent.width - 40); height: Math.min(700, parent.height - 40)
        modal: true; title: root.label("full_report"); standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ColumnLayout {
            Label {
                Layout.fillWidth: true; text: root.label("report_help")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            Components.PixelButton {
                objectName: "intradayProcedureStressCopyReportButton"; text: root.label("copy_report")
                onClicked: root.controller.copyReport()
            }
            ScrollView {
                objectName: "intradayProcedureStressReportScroll"
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                TextArea {
                    objectName: "intradayProcedureStressReportText"
                    width: parent.width; readOnly: true; selectByMouse: true
                    text: report.visible ? root.controller.completedDetails : ""
                    wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
                }
            }
        }
    }
    Dialog {
        id: evidence; objectName: "intradayProcedureStressEvidenceDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(900, parent.width - 40); height: Math.min(650, parent.height - 40)
        modal: true; title: root.label("page_evidence"); standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            objectName: "intradayProcedureStressEvidenceScroll"
            clip: true; contentWidth: availableWidth
            TextArea {
                objectName: "intradayProcedureStressEvidenceText"
                width: parent.width; readOnly: true; selectByMouse: true
                text: evidence.visible ? root.controller.currentPageEvidence : ""
                wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
            }
        }
    }
    ScrollView {
        id: scroll; objectName: "intradayProcedureStressScroll"
        anchors.fill: parent; clip: true; contentWidth: availableWidth
        rightPadding: verticalBar.width
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {
            id: verticalBar; objectName: "intradayProcedureStressScrollBar"
            parent: scroll
            anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right
        }
        ColumnLayout {
            width: scroll.availableWidth; height: Math.max(implicitHeight, scroll.availableHeight)
            spacing: Theme.PixelTheme.spacingSm
            Label {
                objectName: "intradayProcedureStressMethod"
                Layout.fillWidth: true; text: root.label("method")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    objectName: "intradayProcedureStressPath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("source"); text: root.controller.sourcePath
                    onTextChanged: root.controller.setSourcePath(text)
                }
                Components.PixelButton {
                    objectName: "intradayProcedureStressBrowse"; text: root.catalog["quant.browse"]
                    enabled: !operationRuntime.busy; onClicked: sourceFile.open()
                }
                Components.PixelButton {
                    objectName: "intradayProcedureStressOpenButton"; text: root.label("open")
                    enabled: !operationRuntime.busy; onClicked: root.controller.openStudy()
                }
            }
            Label {
                objectName: "intradayProcedureStressSource"
                Layout.fillWidth: true
                text: root.sourceText(root.controller.sourceInfo)
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Flow {
                Layout.fillWidth: true; spacing: Theme.PixelTheme.spacingSm
                Components.PixelButton {
                    objectName: "intradayProcedureStressRunButton"; text: root.label("run")
                    enabled: root.controller.canRun && !operationRuntime.busy; onClicked: root.controller.runStudy()
                }
                Components.PixelButton {
                    objectName: "intradayProcedureStressReportButton"; text: root.label("full_report")
                    enabled: root.controller.resultLoaded; onClicked: report.open()
                }
            }
            Label {
                objectName: "intradayProcedureStressNotice"
                Layout.fillWidth: true
                visible: root.controller.studyError.length > 0 || root.controller.notice.length > 0
                    || root.controller.inputReason.length > 0 || root.controller.draftChanged
                text: root.controller.studyError ? root.controller.studyError + "\n" + root.label("retry")
                    : root.controller.notice ? root.label(root.controller.notice)
                    : root.controller.draftChanged ? root.label("draft_changed") : root.label(root.controller.inputReason)
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            Label {
                objectName: "intradayProcedureStressSummary"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: {
                    const result = root.controller.resultSummary
                    if (!result.status) return ""
                    let summary = root.label("completed") + " · " + root.label(result.status) + "\n" + result.stress_id
                        + "\n" + root.sourceText(root.controller.boundSource)
                        + "\n" + root.label("ordinary_source") + ": " + result.ordinary_source_id
                        + "\n" + root.label("reference") + ": " + JSON.stringify(result.source_selection)
                        + "\n" + root.label("days") + ": " + result.sample_count + " · " + root.label("folds_count") + ": " + result.fold_count
                        + " · " + root.label("available_cells") + ": " + result.scenario_counts.available + " / " + result.scenario_counts.declared
                        + "\n" + root.label(result.basis_matches ? "basis_matched" : "basis_mismatch")
                        + " · " + root.label("projection") + ": " + root.label(result.projection_status)
                        + " · " + root.label("baseline") + ": " + root.label(result.baseline_status)
                        + "\n" + root.label("RECORDED_PRICE_GRID_REEXECUTION")
                    if (result.unavailable_reason) summary += "\n" + root.label(result.unavailable_reason)
                    if (result.detail) summary += "\n" + result.detail
                    return summary
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.ink; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradayProcedureStressInterpretation"
                Layout.fillWidth: true; visible: root.controller.resultLoaded; text: root.label("interpretation")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.LabeledComboBox {
                objectName: "intradayProcedureStressView"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity; enabled: root.controller.resultLoaded
                label: root.catalog["quant.intraday_result_view"]
                model: root.controller.viewOptions.map(key => root.label(key)); currentIndex: root.controller.viewIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.viewIndex)
                onSelected: root.controller.selectView(currentIndex)
            }
            RowLayout {
                Layout.fillWidth: true; visible: root.controller.viewIndex < 5
                Components.LabeledComboBox {
                    objectName: "intradayProcedureStressScenario"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    visible: root.controller.viewIndex !== 4 || root.controller.originIndex === 0
                    label: root.label("scenario"); enabled: root.controller.resultLoaded
                    model: root.controller.scenarioOptions.map(scenario => root.scenarioText(scenario))
                    currentIndex: root.controller.scenarioIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.scenarioIndex)
                    onSelected: root.controller.selectScenario(currentIndex)
                }
                Components.LabeledComboBox {
                    objectName: "intradayProcedureStressRole"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("role"); visible: root.controller.viewIndex !== 2; enabled: root.controller.resultLoaded
                    model: root.controller.roleOptions.map(key => root.label(key)); currentIndex: root.controller.roleIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.roleIndex)
                    onSelected: root.controller.selectRole(currentIndex)
                }
            }
            Label {
                objectName: "intradayProcedureStressScenarioSummary"
                Layout.fillWidth: true
                visible: root.controller.resultLoaded && root.controller.viewIndex < 5
                    && !(root.controller.viewIndex === 4 && root.controller.originIndex === 1)
                text: {
                    const result = root.controller.scenarioSummary
                    if (!result.status) return ""
                    let summary = root.scenarioText(result) + " · " + root.label(result.status)
                        + "\n" + root.label("paired_mean") + ": " + result.mean_display + " " + root.label("PERCENTAGE_POINTS")
                        + " · " + root.label("change_from_zero") + ": " + result.delta_display + " " + root.label("PERCENTAGE_POINTS")
                        + " · " + root.label("days") + ": " + result.sample_count
                    if (root.controller.viewIndex !== 2) {
                        const policy = result.execution_policy
                        summary += "\n" + root.label(result.role) + " · " + root.label("applied_slippage") + ": " + policy.slippage_bps + " bp"
                            + " · " + root.label("entry_delay_minutes") + ": " + policy.entry_delay_minutes
                            + "\n" + root.label("signal_counts") + ": " + JSON.stringify(result.signal_counts)
                    }
                    if (result.unavailable_reason) summary += "\n" + root.label(result.unavailable_reason)
                    if (result.detail) summary += "\n" + result.detail
                    return summary
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true; visible: root.controller.viewIndex === 4
                Components.LabeledComboBox {
                    objectName: "intradayProcedureStressOrigin"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("account_origin"); model: root.controller.originOptions.map(key => root.label(key))
                    currentIndex: root.controller.originIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.originIndex)
                    onSelected: root.controller.selectOrigin(currentIndex)
                }
                Components.LabeledComboBox {
                    objectName: "intradayProcedureStressSection"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity; label: root.label("evidence_section")
                    model: root.controller.sectionOptions.map(key => root.catalog["procedure_stress.account_field." + key] || root.label(key))
                    currentIndex: root.controller.sectionIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.sectionIndex)
                    onSelected: root.controller.selectSection(currentIndex)
                }
            }
            Components.PixelButton {
                objectName: "intradayProcedureStressEvidenceButton"; text: root.label("page_evidence")
                enabled: root.controller.resultLoaded; onClicked: evidence.open()
            }
            Components.DataTable {
                objectName: "intradayProcedureStressTable"
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 210
                paged: true; tableModel: root.controller.tableModel; i18n: root.i18n
                cellFormatter: function(value) { return root.label(value) }
                onPreviousRequested: root.controller.changePage(-1)
                onNextRequested: root.controller.changePage(1)
            }
        }
    }
}
