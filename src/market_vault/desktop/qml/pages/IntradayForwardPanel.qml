import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradayForwardPanel"
    required property var controller
    required property var i18n
    property bool formReady: false

    function label(key) { return root.i18n.catalog["forward." + key] || key }
    function form() {
        return {
            "mode": actionMode.currentIndex === 0 ? "TEMPLATE" : "RECONCILE",
            "experiment_path": experimentPath.text,
            "declaration_path": declarationPath.text,
            "observations_path": observationsPath.text,
            "output_path": outputPath.text,
            "cost_index": costIndex.text,
            "candidate_index": candidateIndex.text
        }
    }
    function syncDraft() { if (formReady) root.controller.setDraft(root.form()) }
    function view(value) { return value === null || value === undefined ? "—" : String(value) }
    Component.onCompleted: { formReady = true; syncDraft() }

    FileDialog {
        id: experimentFile
        objectName: "intradayForwardExperimentDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: { experimentPath.text = selectedFile.toString(); root.syncDraft() }
    }
    FileDialog {
        id: declarationFile
        objectName: "intradayForwardDeclarationDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: { declarationPath.text = selectedFile.toString(); root.syncDraft() }
    }
    FileDialog {
        id: observationsFile
        objectName: "intradayForwardObservationsDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: { observationsPath.text = selectedFile.toString(); root.syncDraft() }
    }
    FileDialog {
        id: outputFile
        objectName: "intradayForwardOutputDialog"
        fileMode: FileDialog.SaveFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: { outputPath.text = selectedFile.toString(); root.syncDraft() }
    }

    ScrollView {
        id: scroll
        objectName: "intradayForwardScroll"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {}
        ColumnLayout {
            width: scroll.availableWidth
            spacing: Theme.PixelTheme.spacingMd

            Label {
                objectName: "intradayForwardMethod"
                Layout.fillWidth: true
                text: root.label("method")
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                Label { text: root.label("mode"); color: Theme.PixelTheme.ink }
                Components.PixelComboBox {
                    id: actionMode
                    objectName: "intradayForwardMode"
                    Layout.preferredWidth: 320
                    model: [root.label("template"), root.label("reconcile")]
                    onActivated: root.syncDraft()
                }
                Item { Layout.fillWidth: true }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    id: experimentPath
                    objectName: "intradayForwardExperimentPath"
                    Layout.maximumWidth: Infinity
                    label: root.label("experiment")
                    placeholderText: root.label("local_path")
                    onEdited: root.syncDraft()
                }
                Components.PixelButton {
                    objectName: "intradayForwardExperimentBrowse"
                    text: root.i18n.catalog["quant.browse"]
                    onClicked: experimentFile.open()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: actionMode.currentIndex === 0
                Components.LabeledTextField {
                    id: declarationPath
                    objectName: "intradayForwardDeclarationPath"
                    Layout.maximumWidth: Infinity
                    label: root.label("declaration")
                    placeholderText: root.label("local_path")
                    onEdited: root.syncDraft()
                }
                Components.PixelButton {
                    objectName: "intradayForwardDeclarationBrowse"
                    text: root.i18n.catalog["quant.browse"]
                    onClicked: declarationFile.open()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: actionMode.currentIndex === 1
                Components.LabeledTextField {
                    id: observationsPath
                    objectName: "intradayForwardObservationsPath"
                    Layout.maximumWidth: Infinity
                    label: root.label("observations")
                    placeholderText: root.label("local_path")
                    onEdited: root.syncDraft()
                }
                Components.PixelButton {
                    objectName: "intradayForwardObservationsBrowse"
                    text: root.i18n.catalog["quant.browse"]
                    onClicked: observationsFile.open()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                visible: actionMode.currentIndex === 0
                Components.LabeledTextField {
                    id: costIndex
                    objectName: "intradayForwardCostIndex"
                    Layout.maximumWidth: 190
                    label: root.label("cost_index")
                    placeholderText: root.label("index_optional")
                    onEdited: root.syncDraft()
                }
                Components.LabeledTextField {
                    id: candidateIndex
                    objectName: "intradayForwardCandidateIndex"
                    Layout.maximumWidth: 190
                    label: root.label("candidate_index")
                    placeholderText: root.label("index_optional")
                    onEdited: root.syncDraft()
                }
                Label {
                    Layout.fillWidth: true
                    text: root.label("indices_help")
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    id: outputPath
                    objectName: "intradayForwardOutputDraft"
                    Layout.maximumWidth: Infinity
                    label: root.label("new_output")
                    placeholderText: root.label("new_output_help")
                    onEdited: root.syncDraft()
                }
                Components.PixelButton {
                    objectName: "intradayForwardOutputBrowse"
                    text: root.i18n.catalog["quant.browse"]
                    onClicked: outputFile.open()
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.PixelButton {
                    objectName: "intradayForwardRun"
                    text: actionMode.currentIndex === 0 ? root.label("export") : root.label("analyze")
                    variant: "primary"
                    enabled: !root.controller.busy && !operationRuntime.busy
                    onClicked: root.controller.run(root.form())
                }
                Label {
                    objectName: "intradayForwardStatus"
                    Layout.fillWidth: true
                    text: root.controller.busy ? root.i18n.catalog["common.running"] :
                          (root.controller.error || root.label(root.controller.notice) || "")
                    color: root.controller.error ? Theme.PixelTheme.vermilionDark : Theme.PixelTheme.inkMuted
                    wrapMode: Text.WrapAnywhere
                }
            }
            Components.PixelPanel {
                visible: root.controller.resultLoaded
                Layout.fillWidth: true
                Layout.preferredHeight: resultColumn.implicitHeight + 32
                padding: Theme.PixelTheme.panelPadding
                ColumnLayout {
                    id: resultColumn
                    anchors.fill: parent
                    spacing: Theme.PixelTheme.spacingSm
                    Label {
                        objectName: "intradayForwardResultKind"
                        text: root.label("result") + ": " + root.controller.resultScope + " / " +
                              root.controller.resultStatus + " / " + root.controller.resultMode
                        color: Theme.PixelTheme.ink
                        font.bold: true
                    }
                    Label {
                        objectName: "intradayForwardCreatedPath"
                        Layout.fillWidth: true
                        text: root.label("output") + ": " + root.controller.outputPath
                        wrapMode: Text.WrapAnywhere
                        color: Theme.PixelTheme.ink
                    }
                    Repeater {
                        model: Object.keys(root.controller.sourceIdentities)
                        delegate: Label {
                            required property string modelData
                            Layout.fillWidth: true
                            text: modelData + ": " + root.view(root.controller.sourceIdentities[modelData])
                            color: Theme.PixelTheme.inkMuted
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                    Repeater {
                        model: ["reference_action_count", "supplied_record_count", "matched_record_count",
                                "unmatched_record_count", "missing_record_count", "measured_quote_count",
                                "quote_policy_exceeded_count"]
                        delegate: Label {
                            required property string modelData
                            Layout.fillWidth: true
                            text: root.label(modelData) + ": " + root.view(root.controller.resultSummary[modelData])
                            color: Theme.PixelTheme.ink
                        }
                    }
                    Repeater {
                        model: Object.keys(root.controller.statistics)
                        delegate: Label {
                            required property string modelData
                            readonly property var metric: root.controller.statistics[modelData]
                            Layout.fillWidth: true
                            text: modelData + ": " + root.label("available") + "=" +
                                  root.view(metric.available_count) + "; " + root.label("unavailable") +
                                  "=" + root.view(metric.unavailable_count) + "; " + root.label("mean") +
                                  "=" + root.view(metric.mean)
                            wrapMode: Text.WrapAnywhere
                            color: Theme.PixelTheme.inkMuted
                        }
                    }
                    Label {
                        objectName: "intradayForwardVerification"
                        Layout.fillWidth: true
                        text: root.label("not_verified")
                        wrapMode: Text.WordWrap
                        color: Theme.PixelTheme.vermilionDark
                    }
                }
            }
            Item { Layout.fillHeight: true }
        }
    }
}
