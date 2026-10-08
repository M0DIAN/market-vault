import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

ColumnLayout {
    id: root
    objectName: "intradayFinalPanel"
    required property var controller
    required property var i18n
    property int bindingRevision: -1
    spacing: Theme.PixelTheme.spacingSm

    function sync() {
        if (bindingRevision !== controller.bindingRevision) {
            bindingRevision = controller.bindingRevision
            sourcePath.text = ""
            dataPath.text = ""
        }
        candidate.currentIndex = controller.researchController.candidateIndex
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
        id: sourcePicker
        objectName: "intradayFinalSourceDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        title: root.i18n.catalog["quant.intraday_source_override"]
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
            Label { Layout.fillWidth: true; text: root.i18n.catalog["quant.intraday_locations_help"]; wrapMode: Text.WordWrap; color: Theme.PixelTheme.ink }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField { id: sourcePath; objectName: "intradayFinalSourcePath"; Layout.fillWidth: true; Layout.maximumWidth: Infinity; label: root.i18n.catalog["quant.intraday_source_override"] }
                Components.PixelButton { objectName: "intradayFinalSourceBrowse"; text: root.i18n.catalog["quant.browse"]; onClicked: sourcePicker.open() }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField { id: dataPath; objectName: "intradayFinalDataPath"; Layout.fillWidth: true; Layout.maximumWidth: Infinity; label: root.i18n.catalog["quant.intraday_data_override"] }
                Components.PixelButton { objectName: "intradayFinalDataBrowse"; text: root.i18n.catalog["quant.browse"]; onClicked: dataPicker.open() }
            }
            RowLayout {
                Components.PixelButton { objectName: "intradayFinalLocationsClear"; text: root.i18n.catalog["quant.intraday_locations_clear"]; onClicked: { sourcePath.text = ""; dataPath.text = "" } }
                Item { Layout.fillWidth: true }
                Components.PixelButton { objectName: "intradayFinalLocationsDone"; text: root.i18n.catalog["quant.intraday_apply_settings"]; onClicked: locations.close() }
            }
        }
    }

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
    Label {
        Layout.fillWidth: true
        text: root.i18n.catalog["quant.intraday_final_help"]
        wrapMode: Text.WordWrap
        color: Theme.PixelTheme.inkMuted
        font.pixelSize: Theme.PixelTheme.fontSm
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
        enabled: !root.controller.busy && !operationRuntime.busy
        Components.PixelButton { objectName: "intradayTestOpenButton"; text: root.i18n.catalog["quant.intraday_test_open"]; onClicked: openTest.open() }
        Components.PixelButton { objectName: "intradayTestSaveButton"; text: root.i18n.catalog["quant.intraday_test_save"]; enabled: root.controller.testLoaded; onClicked: saveTest.open() }
        Components.PixelButton { objectName: "intradayTestReplayButton"; text: root.i18n.catalog["quant.intraday_test_replay"]; enabled: root.controller.testLoaded; onClicked: root.controller.replayTest(sourcePath.text, dataPath.text) }
        Components.PixelButton { objectName: "intradayFinalLocationsButton"; text: root.i18n.catalog["quant.intraday_locations"]; enabled: root.controller.selectionLoaded; onClicked: locations.open() }
    }
    Label {
        Layout.fillWidth: true
        visible: text.length > 0
        text: root.controller.error || ((sourcePath.text || dataPath.text) ? root.i18n.catalog["quant.intraday_locations_active"] : "")
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
                REPLAY_MATCH: "quant.replay_verified", REPLAY_PENDING: "quant.intraday_replay_pending", REPLAY_FAILED: "quant.intraday_replay_failed"}
            for (const key of ["intraday_selection_proof", "intraday_test_proof"]) {
                if (result[key]) result[key] = root.i18n.catalog[keys[result[key]]]
            }
            return result
        }
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
    Components.LabeledComboBox {
        id: view
        objectName: "intradayTestView"
        Layout.fillWidth: true
        Layout.maximumWidth: 350
        visible: root.controller.testLoaded
        label: root.i18n.catalog["quant.intraday_result_view"]
        property int selectedView: 0
        model: ["quant.intraday_overview", "quant.trades", "quant.intraday_ledger", "quant.intraday_daily",
            "quant.intraday_final_model", "quant.intraday_predictions"].map(key => root.i18n.catalog[key])
        onSelected: { selectedView = currentIndex; root.controller.selectView(currentIndex) }
        onModelChanged: currentIndex = selectedView
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
        paged: true
        tableModel: root.controller.tableModel
        i18n: root.i18n
        onPreviousRequested: root.controller.changePage(-1)
        onNextRequested: root.controller.changePage(1)
    }
}
