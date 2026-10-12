import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradaySelectionDiagnosticsPanel"
    required property var controller
    required property var i18n
    readonly property var catalog: i18n.catalog
    function label(key) {
        if (key === undefined || key === null) return "—"
        for (const prefix of ["selection_diagnostics.", "procedure_stress.", "risk.", "performance.", "procedure.", "inner.", "columns."])
            if (root.catalog[prefix + key]) return root.catalog[prefix + key]
        return String(key)
    }
    function sourceText(source) {
        return source.experiment_id ? root.label(source.source_kind) + (source.name ? " · " + source.name : "")
            + "\n" + source.experiment_id + "\n" + source.path : root.label("not_opened")
    }
    function windowText(item) {
        return "#" + item.window_index + " · " + root.label(item.scope)
            + (typeof item.fold_index === "number" ? " #" + item.fold_index : "") + " · " + root.label(item.status)
    }
    function recipeText(item) {
        if (!item) return "—"
        return root.label(item.kind) + " · α=" + root.label(item.alpha) + " · "
            + (typeof item.threshold === "number" ? item.threshold * 10000 + " bp" : "—")
    }
    function scenarioText(item) {
        return "+" + item.additional_slippage_bps + " bp · " + root.label("applied_slippage")
            + " " + item.slippage_bps + " bp · " + root.label(item.status)
    }
    function memberText(item) {
        return "#" + item.candidate_index + " · " + root.label(item.strategy_kind) + " α=" + item.alpha
            + " · " + item.threshold_bps + " bp · " + root.label(item.status)
    }
    FileDialog {
        id: sourceFile; objectName: "intradaySelectionDiagnosticsFileDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.setSourcePath(selectedFile.toString())
    }
    Dialog {
        id: report; objectName: "intradaySelectionDiagnosticsReportDialog"
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
                objectName: "intradaySelectionDiagnosticsCopyReportButton"; text: root.label("copy_report")
                onClicked: root.controller.copyReport()
            }
            ScrollView {
                objectName: "intradaySelectionDiagnosticsReportScroll"
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                TextArea {
                    objectName: "intradaySelectionDiagnosticsReportText"
                    width: parent.width; readOnly: true; selectByMouse: true
                    text: report.visible ? root.controller.completedDetails : ""
                    wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
                }
            }
        }
    }
    Dialog {
        id: evidence; objectName: "intradaySelectionDiagnosticsEvidenceDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(900, parent.width - 40); height: Math.min(650, parent.height - 40)
        modal: true; title: root.label("page_evidence"); standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            objectName: "intradaySelectionDiagnosticsEvidenceScroll"
            clip: true; contentWidth: availableWidth
            TextArea {
                objectName: "intradaySelectionDiagnosticsEvidenceText"
                width: parent.width; readOnly: true; selectByMouse: true
                text: evidence.visible ? root.controller.currentPageEvidence : ""
                wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
            }
        }
    }
    ScrollView {
        id: scroll; objectName: "intradaySelectionDiagnosticsScroll"
        anchors.fill: parent; clip: true; contentWidth: availableWidth
        rightPadding: verticalBar.width
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {
            id: verticalBar; objectName: "intradaySelectionDiagnosticsScrollBar"
            parent: scroll
            anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right
        }
        ColumnLayout {
            width: scroll.availableWidth; height: Math.max(implicitHeight, scroll.availableHeight)
            spacing: Theme.PixelTheme.spacingSm
            Label {
                objectName: "intradaySelectionDiagnosticsMethod"
                Layout.fillWidth: true; text: root.label("method")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    objectName: "intradaySelectionDiagnosticsPath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("source"); text: root.controller.sourcePath
                    onTextChanged: root.controller.setSourcePath(text)
                }
                Components.PixelButton {
                    objectName: "intradaySelectionDiagnosticsBrowse"; text: root.catalog["quant.browse"]
                    enabled: !operationRuntime.busy; onClicked: sourceFile.open()
                }
                Components.PixelButton {
                    objectName: "intradaySelectionDiagnosticsOpenButton"; text: root.label("open")
                    enabled: !operationRuntime.busy; onClicked: root.controller.openStudy()
                }
            }
            Label {
                objectName: "intradaySelectionDiagnosticsSource"
                Layout.fillWidth: true; text: root.sourceText(root.controller.sourceInfo)
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.LabeledComboBox {
                objectName: "intradaySelectionDiagnosticsMode"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity; label: root.label("mode")
                model: root.controller.modeOptions.map(key => root.label(key)); currentIndex: root.controller.modeIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.modeIndex)
                onSelected: root.controller.selectMode(currentIndex)
            }
            Flow {
                Layout.fillWidth: true; spacing: Theme.PixelTheme.spacingSm
                Components.PixelButton {
                    objectName: "intradaySelectionDiagnosticsRunButton"; text: root.label("run")
                    enabled: root.controller.canRun && !operationRuntime.busy; onClicked: root.controller.runStudy()
                }
                Components.PixelButton {
                    objectName: "intradaySelectionDiagnosticsReportButton"; text: root.label("full_report")
                    enabled: root.controller.resultLoaded; onClicked: report.open()
                }
            }
            Label {
                objectName: "intradaySelectionDiagnosticsNotice"
                Layout.fillWidth: true
                visible: root.controller.studyError.length > 0 || root.controller.notice.length > 0
                    || root.controller.inputReason.length > 0 || root.controller.draftChanged
                text: root.controller.studyError ? root.controller.studyError + "\n" + root.label("retry")
                    : root.controller.notice ? root.label(root.controller.notice)
                    : root.controller.draftChanged ? root.label("draft_changed") : root.label(root.controller.inputReason)
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            Label {
                objectName: "intradaySelectionDiagnosticsSummary"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: {
                    const result = root.controller.resultSummary
                    if (!result.status) return ""
                    let text = root.label("completed") + " · " + root.label(result.mode) + " · " + root.label(result.status)
                        + "\n" + root.label("report_id") + ": " + result.report_id
                        + "\n" + root.sourceText(root.controller.boundSource)
                        + "\n" + root.label("source_status") + ": " + root.label(result.source_status)
                        + " · " + root.label("reference") + ": " + JSON.stringify(result.source_selection)
                    if (result.mode === "outer_risk")
                        text += "\n" + root.label("account_availability") + ": " + result.account_availability.available
                            + " / " + result.account_availability.declared + " · " + root.label("comparability")
                            + ": " + root.label(result.comparability.status)
                    else
                        text += "\n" + root.label("family_size") + ": " + result.sample.family_size
                            + " · " + root.label("available_cells") + ": " + result.sample.available_scenario_count
                            + " / " + result.sample.scenario_count
                    if (result.unavailable_reason) text += "\n" + root.label(result.unavailable_reason)
                    return text
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.ink; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradaySelectionDiagnosticsInterpretation"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: root.label(root.controller.completedMode + "_help")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.LabeledComboBox {
                objectName: "intradaySelectionDiagnosticsView"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity; enabled: root.controller.resultLoaded
                label: root.catalog["quant.intraday_result_view"]
                model: root.controller.viewOptions.map(key => root.label(key)); currentIndex: root.controller.viewIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.viewIndex)
                onSelected: root.controller.selectView(currentIndex)
            }
            RowLayout {
                Layout.fillWidth: true; visible: root.controller.resultLoaded && (root.controller.selectors.role || root.controller.selectors.window)
                Components.LabeledComboBox {
                    objectName: "intradaySelectionDiagnosticsRole"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity; visible: root.controller.selectors.role
                    label: root.label("role"); model: root.controller.roleOptions.map(key => root.label(key))
                    currentIndex: root.controller.roleIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.roleIndex)
                    onSelected: root.controller.selectRole(currentIndex)
                }
                Components.LabeledComboBox {
                    objectName: "intradaySelectionDiagnosticsWindow"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity; visible: root.controller.selectors.window
                    label: root.label("window"); model: root.controller.windowOptions.map(item => root.windowText(item))
                    currentIndex: root.controller.windowIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.windowIndex)
                    onSelected: root.controller.selectWindow(currentIndex)
                }
            }
            Components.LabeledComboBox {
                objectName: "intradaySelectionDiagnosticsScenario"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity
                visible: root.controller.resultLoaded && root.controller.selectors.scenario
                label: root.label("scenario"); model: root.controller.scenarioOptions.map(item => root.scenarioText(item))
                currentIndex: root.controller.scenarioIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.scenarioIndex)
                onSelected: root.controller.selectScenario(currentIndex)
            }
            Components.LabeledComboBox {
                objectName: "intradaySelectionDiagnosticsMember"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity
                visible: root.controller.resultLoaded && root.controller.selectors.member
                enabled: root.controller.memberOptions.length > 0
                label: root.label("member"); model: root.controller.memberOptions.map(item => root.memberText(item))
                currentIndex: root.controller.memberIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.memberIndex)
                onSelected: root.controller.selectMember(currentIndex)
            }
            Label {
                objectName: "intradaySelectionDiagnosticsSelectionSummary"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: {
                    const result = root.controller.selectionSummary
                    if (result.role)
                        return root.label(result.role) + " · " + root.label(result.status)
                            + "\n" + root.label("role_diagnostics_id") + ": " + root.label(result.role_diagnostics_id)
                            + (result.unavailable_reason ? "\n" + root.label(result.unavailable_reason) : "")
                            + (result.detail ? "\n" + result.detail : "")
                    if (!result.window) return ""
                    let text = root.windowText(result.window) + " · " + root.label("baseline") + ": " + root.label(result.baseline_status)
                        + "\n" + root.label("original_choice") + ": " + root.label(result.window.original.selected_index)
                        + " · " + root.recipeText(result.window.original.selected_recipe)
                    if (result.baseline_reason) text += "\n" + root.label(result.baseline_reason)
                    if (result.scenario) {
                        const item = result.scenario
                        text += "\n+" + item.additional_slippage_bps + " bp · " + root.label(item.status)
                            + " · " + root.label("new_choice") + ": " + root.label(item.selected_index)
                            + " · " + root.label("gap") + ": " + result.gap_display + " " + root.label("PERCENTAGE_POINTS")
                            + "\n" + root.recipeText(item.selected_recipe) + " · " + root.label("member_counts") + ": "
                            + item.member_counts.declared + " / " + item.member_counts.recorded + " / "
                            + item.member_counts.executed + " / " + item.member_counts.available
                        if (item.unavailable_reason) text += "\n" + root.label(item.unavailable_reason)
                        if (item.detail) text += "\n" + item.detail
                    }
                    if (root.controller.selectors.member)
                        text += "\n" + root.label("member") + ": " + (result.member ? "#" + result.member.candidate_index
                            + " · " + root.label(result.member.status) + " · " + root.recipeText(result.member.recipe) : root.label("NO_RECORDED_MEMBERS"))
                    return text
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.LabeledComboBox {
                objectName: "intradaySelectionDiagnosticsSection"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity
                visible: root.controller.resultLoaded && root.controller.selectors.section
                label: root.label("evidence_section")
                model: root.controller.sectionOptions.map(key => root.catalog["selection_diagnostics.field." + key]
                    || root.catalog["procedure_stress.account_field." + key] || root.label(key))
                currentIndex: root.controller.sectionIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.sectionIndex)
                onSelected: root.controller.selectSection(currentIndex)
            }
            Components.PixelButton {
                objectName: "intradaySelectionDiagnosticsEvidenceButton"; text: root.label("page_evidence")
                enabled: root.controller.resultLoaded; onClicked: evidence.open()
            }
            Components.DataTable {
                objectName: "intradaySelectionDiagnosticsTable"
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 230
                paged: true; tableModel: root.controller.tableModel; i18n: root.i18n
                cellFormatter: function(value) { return root.label(value) }
                onPreviousRequested: root.controller.changePage(-1)
                onNextRequested: root.controller.changePage(1)
            }
        }
    }
}
