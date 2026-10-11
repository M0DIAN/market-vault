import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradaySuitePanel"
    required property var controller
    required property var i18n
    readonly property var catalog: i18n.catalog
    function label(key) {
        for (const prefix of ["suite.", "inner.", "threshold.", "columns.", "status."])
            if (root.catalog[prefix + key]) return root.catalog[prefix + key]
        return key
    }
    function sourceText(source) {
        if (!source.source_id) return root.label("source_required")
        return root.label("source_id") + ": " + source.source_id
            + "\n" + root.label("candidate_id") + ": " + source.candidate_id
            + " · " + root.label("cost_index") + " " + source.cost_index
            + " · " + root.label("candidate_index") + " " + source.candidate_index
            + "\n" + source.source_path
            + (source.data_locator ? "\nQ5 · " + source.data_locator : "")
    }
    FileDialog {
        id: dataFile; objectName: "intradaySuiteDataDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        title: root.label("data")
        onAccepted: root.controller.setDataLocator(selectedFile.toString())
    }
    FileDialog {
        id: saveFile; objectName: "intradaySuiteSaveDialog"
        property int studyIndex: 0
        fileMode: FileDialog.SaveFile; nameFilters: ["JSON files (*.json)"]; defaultSuffix: "json"
        options: FileDialog.DontConfirmOverwrite
        title: root.label("save_path")
        onAccepted: studyRows.itemAt(studyIndex).saveDraft = selectedFile.toString()
    }
    ScrollView {
        id: scroll; objectName: "intradaySuiteScroll"
        anchors.fill: parent; clip: true; contentWidth: availableWidth
        rightPadding: verticalBar.width
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {
            id: verticalBar; objectName: "intradaySuiteScrollBar"
            parent: scroll
            anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right
        }
        ColumnLayout {
            width: scroll.availableWidth
            spacing: Theme.PixelTheme.spacingSm
            Label {
                objectName: "intradaySuiteMethod"
                Layout.fillWidth: true; text: root.label("method")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradaySuiteDraftSource"
                Layout.fillWidth: true
                text: root.label("draft_source") + "\n" + root.sourceText(root.controller.draftSource)
                textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
                color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    objectName: "intradaySuiteDataPath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("data"); text: root.controller.dataLocator
                    onTextChanged: root.controller.setDataLocator(text)
                }
                Components.PixelButton {
                    objectName: "intradaySuiteDataBrowse"; text: root.catalog["quant.browse"]
                    enabled: !operationRuntime.busy; onClicked: dataFile.open()
                }
                Components.PixelButton {
                    objectName: "intradaySuiteRun"; text: root.label("run")
                    enabled: root.controller.canRun && !root.controller.busy && !operationRuntime.busy
                    onClicked: root.controller.runSelected()
                }
            }
            Label {
                objectName: "intradaySuiteStatus"
                Layout.fillWidth: true
                text: root.controller.studyError ? root.controller.studyError + "\n" + root.label("retry")
                    : root.controller.notice ? root.label(root.controller.notice) : root.label(root.controller.status)
                textFormat: Text.PlainText; wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            Label {
                objectName: "intradaySuiteDraftChanged"
                Layout.fillWidth: true; visible: root.controller.draftChanged
                text: root.label("draft_changed"); wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            Label {
                objectName: "intradaySuiteCompletedSource"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: root.label("completed_source") + "\n" + root.sourceText(root.controller.completedSource)
                textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
                color: Theme.PixelTheme.ink; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Repeater {
                id: studyRows
                model: 3
                delegate: ColumnLayout {
                    id: studyRow
                    required property int index
                    readonly property string role: ["Q25", "Q31", "Q36"][index]
                    readonly property var result: root.controller.studyResults[index] || ({})
                    property alias saveDraft: savePath.text
                    Layout.fillWidth: true
                    spacing: Theme.PixelTheme.spacingSm
                    Label {
                        objectName: "intradaySuite" + studyRow.role + "Result"
                        Layout.fillWidth: true
                        text: {
                            const result = studyRow.result
                            const title = root.label(studyRow.role)
                            if (!result.experiment_id) return title + " · " + root.label("not_run")
                            return title + " · " + root.label(result.status) + " · " + root.label(result.save_state)
                                + "\n" + root.label("experiment_id") + ": " + result.experiment_id
                                + "\n" + root.label("selection_id") + ": " + result.selection_id
                                + (result.unavailable_reason ? "\n" + result.unavailable_reason : "")
                                + (result.path ? "\n" + root.label("saved_path") + ": " + result.path : "")
                        }
                        textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
                        color: Theme.PixelTheme.ink; font.pixelSize: Theme.PixelTheme.fontSm
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Components.LabeledTextField {
                            id: savePath
                            objectName: "intradaySuite" + studyRow.role + "SavePath"
                            Layout.fillWidth: true; Layout.maximumWidth: Infinity
                            label: root.label("save_path")
                        }
                        Components.PixelButton {
                            objectName: "intradaySuite" + studyRow.role + "SaveBrowse"
                            text: root.catalog["quant.browse"]; enabled: !operationRuntime.busy
                            onClicked: { saveFile.studyIndex = studyRow.index; saveFile.open() }
                        }
                        Components.PixelButton {
                            objectName: "intradaySuite" + studyRow.role + "Save"
                            text: root.label("save")
                            enabled: root.controller.resultLoaded && !root.controller.busy && !operationRuntime.busy
                            onClicked: root.controller.saveStudy(studyRow.index, savePath.text)
                        }
                        Components.PixelButton {
                            objectName: "intradaySuite" + studyRow.role + "View"
                            text: root.label("view")
                            enabled: root.controller.resultLoaded && !root.controller.busy && !operationRuntime.busy
                            onClicked: root.controller.viewStudy(studyRow.index)
                        }
                    }
                }
            }
            Components.PixelButton {
                objectName: "intradaySuiteCompare"; text: root.label("compare")
                enabled: root.controller.canCompare && !root.controller.busy && !operationRuntime.busy
                onClicked: root.controller.compareSaved()
            }
        }
    }
}
