import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradayProcedurePanel"
    required property var controller
    required property var i18n
    function label(key) {
        return root.i18n.catalog["procedure." + key] || root.i18n.catalog["ml_diagnostics." + key]
            || root.i18n.catalog["uncertainty." + key] || root.i18n.catalog["inner." + key] || key
    }
    function sourceText(source) {
        return source.experiment_id ? root.label(source.source_kind) + (source.name ? " · " + source.name : "")
            + "\n" + source.experiment_id : root.label("not_opened")
    }
    FileDialog {
        id: leftFile; objectName: "intradayProcedureLeftDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.setLeftPath(selectedFile.toString())
    }
    FileDialog {
        id: rightFile; objectName: "intradayProcedureRightDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.setRightPath(selectedFile.toString())
    }
    Dialog {
        id: report; objectName: "intradayProcedureReportDialog"
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
                objectName: "intradayProcedureCopyReportButton"; text: root.label("copy_report")
                onClicked: root.controller.copyReport()
            }
            ScrollView {
                objectName: "intradayProcedureReportScroll"
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true; contentWidth: availableWidth
                TextArea {
                    objectName: "intradayProcedureReportText"
                    width: parent.width; readOnly: true; selectByMouse: true
                    text: report.visible ? root.controller.completedDetails : ""
                    wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
                }
            }
        }
    }
    Dialog {
        id: evidence; objectName: "intradayProcedureEvidenceDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(900, parent.width - 40); height: Math.min(650, parent.height - 40)
        modal: true; title: root.label("page_evidence"); standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            objectName: "intradayProcedureEvidenceScroll"
            clip: true; contentWidth: availableWidth
            TextArea {
                objectName: "intradayProcedureEvidenceText"
                width: parent.width; readOnly: true; selectByMouse: true
                text: evidence.visible ? root.controller.currentPageEvidence : ""
                wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
            }
        }
    }
    ScrollView {
        id: scroll; objectName: "intradayProcedureScroll"
        anchors.fill: parent; clip: true; contentWidth: availableWidth
        rightPadding: verticalBar.width
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {
            id: verticalBar; objectName: "intradayProcedureScrollBar"
            parent: scroll
            anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right
        }
        ColumnLayout {
            width: scroll.availableWidth; height: Math.max(implicitHeight, scroll.availableHeight)
            spacing: Theme.PixelTheme.spacingSm
            Label {
                objectName: "intradayProcedureMethod"
                Layout.fillWidth: true; text: root.label("method")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    objectName: "intradayProcedureLeftPath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("source_a"); text: root.controller.leftPath
                    onTextChanged: root.controller.setLeftPath(text)
                }
                Components.PixelButton {
                    objectName: "intradayProcedureLeftBrowse"; text: root.i18n.catalog["quant.browse"]
                    enabled: !operationRuntime.busy; onClicked: leftFile.open()
                }
                Components.PixelButton {
                    objectName: "intradayProcedureOpenLeftButton"; text: root.label("open_a")
                    enabled: !operationRuntime.busy; onClicked: root.controller.openLeft()
                }
            }
            Label {
                objectName: "intradayProcedureLeftSource"
                Layout.fillWidth: true
                text: { root.i18n.language; return root.sourceText(root.controller.leftSource) }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    objectName: "intradayProcedureRightPath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("source_b"); text: root.controller.rightPath
                    onTextChanged: root.controller.setRightPath(text)
                }
                Components.PixelButton {
                    objectName: "intradayProcedureRightBrowse"; text: root.i18n.catalog["quant.browse"]
                    enabled: !operationRuntime.busy; onClicked: rightFile.open()
                }
                Components.PixelButton {
                    objectName: "intradayProcedureOpenRightButton"; text: root.label("open_b")
                    enabled: !operationRuntime.busy; onClicked: root.controller.openRight()
                }
            }
            Label {
                objectName: "intradayProcedureRightSource"
                Layout.fillWidth: true
                text: { root.i18n.language; return root.sourceText(root.controller.rightSource) }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Flow {
                Layout.fillWidth: true; spacing: Theme.PixelTheme.spacingSm
                Components.PixelButton {
                    objectName: "intradayProcedureOpenPairButton"; text: root.label("open_pair")
                    enabled: !operationRuntime.busy; onClicked: root.controller.openPair()
                }
                Components.PixelButton {
                    objectName: "intradayProcedureRunButton"; text: root.label("run")
                    enabled: root.controller.canRun && !operationRuntime.busy; onClicked: root.controller.runComparison()
                }
                Components.PixelButton {
                    objectName: "intradayProcedureReportButton"; text: root.label("full_report")
                    enabled: root.controller.resultLoaded; onClicked: report.open()
                }
            }
            Label {
                objectName: "intradayProcedureNotice"
                Layout.fillWidth: true
                visible: root.controller.studyError.length > 0 || root.controller.notice.length > 0
                    || root.controller.inputReason.length > 0 || root.controller.draftChanged
                text: root.controller.studyError ? root.controller.studyError + "\n" + root.label("retry")
                    : root.controller.notice ? root.label(root.controller.notice)
                    : root.controller.draftChanged ? root.label("draft_changed") : root.label(root.controller.inputReason)
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            Label {
                objectName: "intradayProcedureSummary"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: {
                    root.i18n.language
                    const result = root.controller.resultSummary, sample = result.sample, sampling = result.sampling
                    if (!result.status) return ""
                    let summary = root.label("completed") + " · " + root.label(result.status) + "\n" + result.comparison_id
                    for (const source of root.controller.boundSources)
                        summary += "\n" + source.role + " · " + root.label(source.source_kind) + (source.name ? " · " + source.name : "")
                            + "\n" + source.experiment_id + "\n" + source.path
                    summary += "\n" + root.label("ordinary_source") + ": " + result.ordinary_source_id
                        + "\n" + root.label("reference") + ": " + JSON.stringify(result.source_selection)
                    if (sample) summary += "\n" + root.label("days") + ": " + sample.sample_count
                        + " · " + root.label("folds_count") + ": " + sample.fold_count
                        + " · " + sample.first_day + " – " + sample.last_day
                    if (sampling) summary += "\n" + root.label("replications") + ": " + sampling.replications
                        + " · " + root.label("seed") + ": " + sampling.seed + " · " + root.label("block_days") + ": " + sampling.block_days
                        + " · " + root.label(result.basis_matches ? "basis_matched" : "basis_mismatch")
                    if (result.unavailable_reason) summary += "\n" + root.label(result.unavailable_reason)
                        + "\n" + JSON.stringify(result.unavailable_reasons)
                    return summary
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.ink; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradayProcedureInterpretation"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: root.label("interpretation")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledComboBox {
                    objectName: "intradayProcedureView"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.intraday_result_view"]
                    model: root.controller.viewOptions.map(key => root.label(key)); currentIndex: root.controller.viewIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.viewIndex)
                    onSelected: root.controller.selectView(currentIndex)
                }
                Components.LabeledComboBox {
                    objectName: "intradayProcedureMember"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    visible: root.controller.viewIndex === 2 || root.controller.viewIndex === 3
                    label: root.label("member"); model: root.controller.memberOptions.map(key => root.label(key))
                    currentIndex: root.controller.memberIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.memberIndex)
                    onSelected: root.controller.selectMember(currentIndex)
                }
            }
            Components.LabeledComboBox {
                objectName: "intradayProcedureSection"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity; visible: root.controller.viewIndex === 3
                label: root.label("evidence_section")
                model: root.controller.sectionOptions.map(key => root.i18n.catalog["ml_diagnostics.account_field." + key] || key)
                currentIndex: root.controller.sectionIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.sectionIndex)
                onSelected: root.controller.selectSection(currentIndex)
            }
            Components.PixelButton {
                objectName: "intradayProcedureEvidenceButton"; text: root.label("page_evidence")
                enabled: root.controller.resultLoaded; onClicked: evidence.open()
            }
            Components.DataTable {
                objectName: "intradayProcedureTable"
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 210
                paged: true; tableModel: root.controller.tableModel; i18n: root.i18n
                cellFormatter: function(value) {
                    root.i18n.language
                    for (const prefix of ["procedure.", "uncertainty.", "ml_diagnostics.", "inner.", "columns."]) {
                        const key = prefix + value, translated = root.i18n.translate(key)
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
