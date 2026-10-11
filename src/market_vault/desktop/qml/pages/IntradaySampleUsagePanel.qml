import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradaySampleUsagePanel"
    required property var controller
    required property var i18n
    readonly property var catalog: i18n.catalog
    function label(key) {
        if (key === undefined || key === null) return ""
        for (const prefix of ["sample_usage.", "ml_diagnostics.", "inner.", "columns."])
            if (root.catalog[prefix + key]) return root.catalog[prefix + key]
        return key
    }
    function stageText(stage) {
        return "#" + stage.stage_index + " · " + root.label(stage.scope) + " · " + root.label(stage.stage_kind)
            + (typeof stage.fold_index === "number" ? " · " + root.label("fold") + " " + stage.fold_index : "")
    }
    function supportText(key, counts) {
        if (!counts) return ""
        return root.label(key) + ": " + root.label("different_samples") + " " + counts.different_sample_count
            + " · " + root.label("incomplete_evidence") + " " + counts.incomplete_evidence_sample_count
            + " · " + root.label("applicable") + " " + counts.applicable_sample_count
            + " / " + root.label("recorded") + " " + counts.recorded_sample_count
            + " · " + root.label("not_applicable") + " " + counts.not_applicable_sample_count
    }
    FileDialog {
        id: sourceFile; objectName: "intradaySampleUsageSourceDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        title: root.label("source")
        onAccepted: root.controller.setSourcePath(selectedFile.toString())
    }
    FileDialog {
        id: manifestFile; objectName: "intradaySampleUsageManifestDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        title: root.label("manifest")
        onAccepted: root.controller.setManifestPath(selectedFile.toString())
    }
    FileDialog {
        id: dataFile; objectName: "intradaySampleUsageDataDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        title: root.label("data")
        onAccepted: root.controller.setDataLocator(selectedFile.toString())
    }
    FileDialog {
        id: saveFile; objectName: "intradaySampleUsageSaveDialog"
        fileMode: FileDialog.SaveFile; nameFilters: ["JSON files (*.json)"]; defaultSuffix: "json"
        options: FileDialog.DontConfirmOverwrite
        title: root.label("save")
        onAccepted: root.controller.saveReport(selectedFile.toString())
    }
    Dialog {
        id: report; objectName: "intradaySampleUsageReportDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(950, parent.width - 40); height: Math.min(700, parent.height - 40)
        modal: true; title: root.label("full_report"); standardButtons: Dialog.Close
        onClosed: reportSection.currentIndex = 0
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ColumnLayout {
            Label {
                Layout.fillWidth: true; text: root.label("report_help")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            Components.LabeledComboBox {
                id: reportSection; objectName: "intradaySampleUsageReportSection"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity
                label: root.label("report_section")
                model: [root.label("report_identity"), root.label("report_json")]; currentIndex: 0
            }
            ScrollView {
                objectName: "intradaySampleUsageReportScroll"
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
                TextArea {
                    objectName: "intradaySampleUsageReportText"
                    width: parent.width; readOnly: true; selectByMouse: true
                    text: report.visible ? (reportSection.currentIndex === 0
                        ? root.controller.completedDetails : root.controller.completeReport) : ""
                    wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
                }
            }
        }
    }
    Dialog {
        id: evidence; objectName: "intradaySampleUsageEvidenceDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(900, parent.width - 40); height: Math.min(650, parent.height - 40)
        modal: true; title: root.label("page_evidence"); standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            objectName: "intradaySampleUsageEvidenceScroll"
            clip: true; contentWidth: availableWidth
            TextArea {
                objectName: "intradaySampleUsageEvidenceText"
                width: parent.width; readOnly: true; selectByMouse: true
                text: evidence.visible ? root.controller.currentPageEvidence : ""
                wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
            }
        }
    }
    ScrollView {
        id: scroll; objectName: "intradaySampleUsageScroll"
        anchors.fill: parent; clip: true; contentWidth: availableWidth
        rightPadding: verticalBar.width
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {
            id: verticalBar; objectName: "intradaySampleUsageScrollBar"
            parent: scroll
            anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right
        }
        ColumnLayout {
            width: scroll.availableWidth; height: Math.max(implicitHeight, scroll.availableHeight)
            spacing: Theme.PixelTheme.spacingSm
            Label {
                objectName: "intradaySampleUsageMethod"
                Layout.fillWidth: true; text: root.label("method")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    objectName: "intradaySampleUsageSourcePath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("source"); text: root.controller.sourcePath
                    onTextChanged: root.controller.setSourcePath(text)
                }
                Components.PixelButton {
                    objectName: "intradaySampleUsageSourceBrowse"; text: root.catalog["quant.browse"]
                    enabled: !operationRuntime.busy; onClicked: sourceFile.open()
                }
                Components.PixelButton {
                    objectName: "intradaySampleUsageOpenButton"; text: root.label("open")
                    enabled: !operationRuntime.busy; onClicked: root.controller.openSource()
                }
            }
            Label {
                objectName: "intradaySampleUsageSource"
                Layout.fillWidth: true
                text: {
                    const source = root.controller.sourceInfo
                    if (!source.experiment_id) return root.label("not_opened")
                    return root.label("opened") + " · " + root.label(source.source_kind)
                        + (source.name ? " · " + source.name : "") + "\n" + source.experiment_id
                        + "\n" + source.path + "\n" + root.label("content_sha") + ": " + source.content_sha256
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true; visible: root.controller.ordinarySource
                Components.LabeledComboBox {
                    objectName: "intradaySampleUsageCost"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("cost"); model: root.controller.costNames
                    currentIndex: root.controller.costIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.costIndex)
                    onSelected: root.controller.selectCost(currentIndex)
                }
                Components.LabeledComboBox {
                    objectName: "intradaySampleUsageCandidate"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("candidate"); model: root.controller.candidateNames
                    currentIndex: root.controller.candidateIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.candidateIndex)
                    onSelected: root.controller.selectCandidate(currentIndex)
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    objectName: "intradaySampleUsageManifestPath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("manifest"); text: root.controller.manifestPath
                    onTextChanged: root.controller.setManifestPath(text)
                }
                Components.PixelButton {
                    objectName: "intradaySampleUsageManifestBrowse"; text: root.catalog["quant.browse"]
                    enabled: !operationRuntime.busy; onClicked: manifestFile.open()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    objectName: "intradaySampleUsageDataPath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("data"); text: root.controller.dataLocator
                    onTextChanged: root.controller.setDataLocator(text)
                }
                Components.PixelButton {
                    objectName: "intradaySampleUsageDataBrowse"; text: root.catalog["quant.browse"]
                    enabled: !operationRuntime.busy; onClicked: dataFile.open()
                }
                Components.PixelButton {
                    objectName: "intradaySampleUsageDataClear"; text: root.label("clear")
                    onClicked: root.controller.setDataLocator("")
                }
            }
            Flow {
                Layout.fillWidth: true; spacing: Theme.PixelTheme.spacingSm
                Components.PixelButton {
                    objectName: "intradaySampleUsageRunButton"; text: root.label("run")
                    enabled: root.controller.canRun && !operationRuntime.busy; onClicked: root.controller.runSelected()
                }
                Components.PixelButton {
                    objectName: "intradaySampleUsageReportButton"; text: root.label("full_report")
                    enabled: root.controller.resultLoaded; onClicked: report.open()
                }
                Components.PixelButton {
                    objectName: "intradaySampleUsageCopyReportButton"; text: root.label("copy_report")
                    enabled: root.controller.resultLoaded; onClicked: root.controller.copyReport()
                }
                Components.PixelButton {
                    objectName: "intradaySampleUsageSaveButton"; text: root.label("save")
                    enabled: root.controller.resultLoaded && !operationRuntime.busy; onClicked: saveFile.open()
                }
            }
            Label {
                objectName: "intradaySampleUsageNotice"
                Layout.fillWidth: true
                visible: root.controller.studyError.length > 0 || root.controller.notice.length > 0
                    || root.controller.inputReason.length > 0 || root.controller.draftChanged
                text: root.controller.studyError ? root.controller.studyError + "\n" + root.label("retry")
                    : root.controller.notice ? root.label(root.controller.notice)
                    : root.controller.draftChanged ? root.label("draft_changed") : root.label(root.controller.inputReason)
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            Label {
                objectName: "intradaySampleUsageSavedPath"
                Layout.fillWidth: true; visible: root.controller.savedPath.length > 0
                text: root.label("saved") + ": " + root.controller.savedPath
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradaySampleUsageSummary"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: {
                    const result = root.controller.resultSummary, capture = root.controller.boundSource
                    if (!result.status) return ""
                    const summary = result.summary, market = result.market_summary, selection = result.source.source_selection
                    return root.label("completed") + " · " + root.label(result.status)
                        + "\n" + capture.sample_usage_id + "\n" + root.label(result.source.source_kind) + " · " + result.source.experiment_id
                        + "\n" + root.label("content_sha") + ": " + capture.opened_source_content_sha256
                        + "\n" + root.label("completed_selection") + ": " + selection.cost_index + " / " + selection.candidate_index
                        + " · " + root.label("stages_count") + ": " + summary.stage_count
                        + " · " + root.label("actual_memberships") + ": " + summary.actual_used_sample_memberships
                        + " / " + root.label("recorded_memberships") + ": " + summary.recorded_sample_memberships
                        + "\n" + root.label("market_coverage") + ": " + root.label(result.market_status)
                        + " · " + root.label("compared_slots") + ": " + market.numerically_compared_slots + " / " + market.expected_slots
                        + " · " + root.label("missing_slots") + ": " + market.local_missing_slots
                        + "\n" + root.label("observations") + ": " + result.observation_count
                        + " · " + root.label("target_horizon") + ": " + (result.target_horizon_bars === null
                            ? root.label("NO_TARGET") : result.target_horizon_bars)
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.ink; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradaySampleUsageInterpretation"
                Layout.fillWidth: true; visible: root.controller.resultLoaded; text: root.label("interpretation")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.LabeledComboBox {
                objectName: "intradaySampleUsageView"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity; enabled: root.controller.resultLoaded
                label: root.catalog["quant.intraday_result_view"]
                model: root.controller.viewOptions.map(key => root.label(key)); currentIndex: root.controller.viewIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.viewIndex)
                onSelected: root.controller.selectView(currentIndex)
            }
            Components.LabeledComboBox {
                objectName: "intradaySampleUsageStage"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity
                visible: root.controller.viewIndex >= 2; enabled: root.controller.resultLoaded
                label: root.label("stage"); model: root.controller.stageOptions.map(stage => root.stageText(stage))
                currentIndex: root.controller.stageIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.stageIndex)
                onSelected: root.controller.selectStage(currentIndex)
            }
            Label {
                objectName: "intradaySampleUsageSupportHelp"
                Layout.fillWidth: true; visible: root.controller.resultLoaded && root.controller.viewIndex === 1
                text: root.label("support_help")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradaySampleUsageStageSummary"
                Layout.fillWidth: true; visible: root.controller.resultLoaded && root.controller.viewIndex >= 2
                text: {
                    const stage = root.controller.stageSummary
                    if (!stage.stage_kind) return ""
                    const counts = stage.support_counts
                    return root.stageText(stage) + " · " + root.label(stage.usage)
                        + "\n" + root.label("recorded_samples") + ": " + stage.recorded_sample_count
                        + " · " + root.label("actual_samples") + ": " + stage.actual_used_count
                        + " · " + root.label("fit_origin") + ": " + root.label(stage.fit_origin)
                        + "\n" + root.label("feature_usage") + ": " + root.label(stage.feature_usage)
                        + " · " + root.label("label_usage") + ": " + root.label(stage.label_usage)
                        + "\n" + root.supportText("feature_window", counts.feature_window)
                        + "\n" + root.supportText("target_endpoints", counts.target_endpoints)
                        + "\n" + root.supportText("target_completeness", counts.target_completeness)
                        + "\n" + root.label("recorded_prices") + ": " + stage.recorded_price_slot_count
                        + " · " + root.label("actual_prices") + ": " + stage.actual_used_price_slot_count
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.LabeledComboBox {
                objectName: "intradaySampleUsageBarScope"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity
                visible: root.controller.viewIndex === 3; enabled: root.controller.resultLoaded
                label: root.label("bar_scope"); model: root.controller.barScopeOptions.map(key => root.label(key))
                currentIndex: root.controller.barScopeIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.barScopeIndex)
                onSelected: root.controller.selectBarScope(currentIndex)
            }
            Components.LabeledComboBox {
                objectName: "intradaySampleUsageSample"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity
                visible: root.controller.viewIndex === 3 && root.controller.barScopeIndex === 0
                enabled: root.controller.resultLoaded; label: root.label("sample")
                model: root.controller.sampleOptions.map(sample => "#" + sample.sample_ref + " · " + sample.observation_key)
                currentIndex: root.controller.sampleIndex
                onModelChanged: currentIndex = Qt.binding(() => root.controller.sampleIndex)
                onSelected: root.controller.selectSample(currentIndex)
            }
            Components.PixelButton {
                objectName: "intradaySampleUsageEvidenceButton"; text: root.label("page_evidence")
                enabled: root.controller.resultLoaded; onClicked: evidence.open()
            }
            Components.DataTable {
                objectName: "intradaySampleUsageTable"
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 210
                paged: true; tableModel: root.controller.tableModel; i18n: root.i18n
                cellFormatter: function(value) { return root.label(value) }
                onPreviousRequested: root.controller.changePage(-1)
                onNextRequested: root.controller.changePage(1)
            }
        }
    }
}
