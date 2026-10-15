import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradayDataAcceptancePanel"
    required property var controller
    required property var i18n
    property bool formReady: false
    function label(key) { return root.i18n.catalog["acceptance." + key] || key }
    function form() { return {data_path: dataPath.text, manifest_path: manifestPath.text, policy_path: policyPath.text} }
    function syncDraft() { if (formReady) root.controller.setDraft(root.form()) }
    Component.onCompleted: { formReady = true; syncDraft() }

    FileDialog {
        id: dataFile
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: { dataPath.text = selectedFile.toString(); root.syncDraft() }
    }
    FileDialog {
        id: manifestFile
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: { manifestPath.text = selectedFile.toString(); root.syncDraft() }
    }
    FileDialog {
        id: policyFile
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        onAccepted: { policyPath.text = selectedFile.toString(); root.syncDraft() }
    }
    FileDialog {
        id: exportFile
        objectName: "intradayAcceptanceExportDialog"
        title: root.label("export")
        fileMode: FileDialog.SaveFile
        options: FileDialog.DontConfirmOverwrite
        nameFilters: ["JSON files (*.json)"]
        defaultSuffix: "json"
        onAccepted: root.controller.exportReport(selectedFile.toString())
    }
    Dialog {
        id: details
        objectName: "intradayAcceptanceDetailsDialog"
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(960, parent ? parent.width - 32 : 960)
        height: Math.max(1, Math.min(620, parent ? parent.height - 24 : 620))
        title: root.label("details")
        standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            clip: true
            TextArea {
                objectName: "intradayAcceptanceDetails"
                text: root.controller.reportJson
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.WrapAnywhere
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
        }
    }
    ScrollView {
        id: scroll
        objectName: "intradayAcceptanceScroll"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {}
        ColumnLayout {
            width: scroll.availableWidth
            spacing: Theme.PixelTheme.spacingSm
            Label {
                Layout.fillWidth: true
                text: root.label("method")
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    id: dataPath
                    objectName: "intradayAcceptanceDataPath"
                    Layout.maximumWidth: Infinity
                    label: root.label("data")
                    placeholderText: root.i18n.catalog["forward.local_path"]
                    onEdited: root.syncDraft()
                }
                Components.PixelButton { text: root.i18n.catalog["quant.browse"]; onClicked: dataFile.open() }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    id: manifestPath
                    objectName: "intradayAcceptanceManifestPath"
                    Layout.maximumWidth: Infinity
                    label: root.label("manifest")
                    placeholderText: root.i18n.catalog["forward.local_path"]
                    onEdited: root.syncDraft()
                }
                Components.PixelButton { text: root.i18n.catalog["quant.browse"]; onClicked: manifestFile.open() }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    id: policyPath
                    objectName: "intradayAcceptancePolicyPath"
                    Layout.maximumWidth: Infinity
                    label: root.label("policy")
                    placeholderText: root.i18n.catalog["forward.local_path"]
                    onEdited: root.syncDraft()
                }
                Components.PixelButton { text: root.i18n.catalog["quant.browse"]; onClicked: policyFile.open() }
            }
            Flow {
                Layout.fillWidth: true
                spacing: Theme.PixelTheme.spacingSm
                Components.PixelButton {
                    objectName: "intradayAcceptanceRun"
                    text: root.label("analyze")
                    variant: "primary"
                    enabled: !root.controller.busy && !operationRuntime.busy
                    onClicked: root.controller.run(root.form())
                }
                Components.PixelButton {
                    objectName: "intradayAcceptanceExport"
                    text: root.label("export")
                    enabled: root.controller.resultLoaded && !root.controller.busy && !operationRuntime.busy
                    onClicked: exportFile.open()
                }
                Components.PixelButton {
                    objectName: "intradayAcceptanceShowDetails"
                    text: root.label("details")
                    enabled: root.controller.resultLoaded
                    onClicked: details.open()
                }
            }
            Label {
                objectName: "intradayAcceptanceNotice"
                Layout.fillWidth: true
                text: root.controller.busy ? root.i18n.catalog["common.running"] :
                    (root.controller.error || root.label(root.controller.notice))
                wrapMode: Text.WrapAnywhere
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradayAcceptanceStatus"
                Layout.fillWidth: true
                visible: root.controller.resultLoaded
                text: root.controller.resultStatus + " · " + root.label(root.controller.resultStatus)
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.bold: true
            }
            Label {
                objectName: "intradayAcceptanceDenominator"
                Layout.fillWidth: true
                visible: root.controller.resultLoaded
                text: root.label("coverage") + ": " + root.controller.resultSummary.numerically_compared_slots
                    + " / " + root.controller.resultSummary.expected_slots + "\n"
                    + JSON.stringify(root.controller.resultSummary.counts || {})
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
            }
            Label {
                objectName: "intradayAcceptanceAssurance"
                Layout.fillWidth: true
                text: root.label("assurance")
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Repeater {
                model: Object.keys(root.controller.resultIdentities)
                delegate: Label {
                    required property string modelData
                    Layout.fillWidth: true
                    text: modelData + ": " + root.controller.resultIdentities[modelData]
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
            Label {
                Layout.fillWidth: true
                visible: root.controller.resultLoaded
                text: root.label("reasons")
                color: Theme.PixelTheme.ink
            }
            ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: 160
                visible: root.controller.resultLoaded
                clip: true
                TextArea {
                    objectName: "intradayAcceptanceReasons"
                    text: root.controller.reasonsJson
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.WrapAnywhere
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
            Label {
                objectName: "intradayAcceptanceReceipt"
                Layout.fillWidth: true
                visible: !!root.controller.exportReceipt.path
                text: root.label("saved") + ": " + (root.controller.exportReceipt.path || "")
                    + "\nacceptance_id: " + (root.controller.exportReceipt.acceptance_id || "")
                wrapMode: Text.WrapAnywhere
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
        }
    }
}
