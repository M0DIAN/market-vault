import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradayInnerPanel"
    required property var controller
    required property var i18n
    function sync() {
        candidate.currentIndex = controller.researchController.candidateIndex
        equity.requestPaint()
    }
    Component.onCompleted: sync()
    Connections { target: root.controller; function onChanged() { root.sync() } }
    FileDialog {
        id: openFile; objectName: "intradayInnerOpenDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        title: root.i18n.catalog["inner.open"]
        onAccepted: root.controller.openExperiment(selectedFile.toString())
    }
    FileDialog {
        id: saveFile; objectName: "intradayInnerSaveDialog"
        fileMode: FileDialog.SaveFile; nameFilters: ["JSON files (*.json)"]; defaultSuffix: "json"
        title: root.i18n.catalog["inner.save"]
        onAccepted: root.controller.saveExperiment(selectedFile.toString())
    }
    FileDialog {
        id: dataFile; objectName: "intradayInnerDataDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.setDataLocator(selectedFile.toString())
    }
    Dialog {
        id: details; objectName: "intradayInnerDetailsDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(850, parent.width - 40); height: Math.min(520, parent.height - 40)
        modal: true; title: root.i18n.catalog["inner.details"]
        standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            clip: true; contentWidth: availableWidth
            Label {
                width: parent.width
                text: {
                    root.i18n.language
                    const values = root.controller.completedDetails
                    return Object.keys(values).map(key => {
                        const value = key === "unavailable_reasons" ? values[key].map(row =>
                            (root.i18n.catalog["inner." + row.scope] || row.scope) + " " + (row.fold_index === null ? "" : row.fold_index)
                            + ": " + (root.i18n.catalog["inner." + row.reason] || row.reason)).join("\n") : values[key]
                        return (root.i18n.catalog["inner." + key] || key) + ": " + value
                    }).join("\n")
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.ink
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingSm
        Label {
            Layout.fillWidth: true; text: root.i18n.catalog["inner.method"]
            wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
        }
        RowLayout {
            Layout.fillWidth: true
            Components.LabeledComboBox {
                id: candidate; objectName: "intradayInnerCandidate"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity
                label: root.i18n.catalog["inner.source"]
                model: root.controller.researchController.candidateNames
                onSelected: root.controller.researchController.selectCandidate(currentIndex)
                onModelChanged: currentIndex = root.controller.researchController.candidateIndex
            }
            Components.PixelButton {
                objectName: "intradayInnerRunButton"; text: root.i18n.catalog["inner.run"]
                enabled: root.controller.canRun && !operationRuntime.busy
                onClicked: root.controller.runSelected()
            }
            Components.PixelButton {
                objectName: "intradayInnerDetailsButton"; text: root.i18n.catalog["inner.details"]
                enabled: root.controller.resultLoaded; onClicked: details.open()
            }
        }
        Label {
            Layout.fillWidth: true; visible: !root.controller.canRun
            text: root.i18n.catalog["inner.source_required"]; wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
        }
        RowLayout {
            Layout.fillWidth: true
            Components.LabeledTextField {
                id: dataPath; objectName: "intradayInnerDataPath"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity
                label: root.i18n.catalog["inner.data"]
                text: root.controller.dataLocator
                onTextChanged: root.controller.setDataLocator(text)
            }
            Components.PixelButton { objectName: "intradayInnerDataBrowse"; text: root.i18n.catalog["quant.browse"]; onClicked: dataFile.open() }
            Components.PixelButton { objectName: "intradayInnerDataClear"; text: root.i18n.catalog["inner.clear"]; onClicked: root.controller.setDataLocator("") }
        }
        Components.SummaryStrip { Layout.fillWidth: true; summary: root.controller.resultSummary; i18n: root.i18n }
        Label {
            objectName: "intradayInnerFinalRecipe"; Layout.fillWidth: true; visible: root.controller.resultLoaded
            text: root.i18n.catalog["inner.final_recipe"] + ": " + (root.controller.finalRecipe.kind
                ? root.controller.finalRecipe.kind + " · alpha=" + root.controller.finalRecipe.alpha + " · threshold=" + root.controller.finalRecipe.threshold
                : root.i18n.catalog["inner.UNAVAILABLE"])
            wrapMode: Text.WordWrap; color: Theme.PixelTheme.ink
        }
        Label {
            Layout.fillWidth: true; visible: root.controller.notice.length > 0 || root.controller.studyError.length > 0
            text: root.controller.studyError || root.i18n.catalog["inner." + root.controller.notice]
            wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
        }
        RowLayout {
            Layout.fillWidth: true
            Components.PixelButton { objectName: "intradayInnerOpenButton"; text: root.i18n.catalog["inner.open"]; enabled: !operationRuntime.busy; onClicked: openFile.open() }
            Components.PixelButton { objectName: "intradayInnerSaveButton"; text: root.i18n.catalog["inner.save"]; enabled: root.controller.resultLoaded && !operationRuntime.busy; onClicked: saveFile.open() }
            Components.PixelButton { objectName: "intradayInnerReplayButton"; text: root.i18n.catalog["inner.replay"]; enabled: root.controller.resultLoaded && !operationRuntime.busy; onClicked: root.controller.replayExperiment() }
            Components.LabeledComboBox {
                id: view; objectName: "intradayInnerView"
                Layout.fillWidth: true; Layout.maximumWidth: Infinity
                label: root.i18n.catalog["quant.intraday_result_view"]; property int selectedView: 0
                model: ["inner.overview", "inner.family", "inner.keys", "inner.models", "inner.inner_predictions", "inner.outer_predictions",
                    "quant.trades", "quant.intraday_daily", "quant.intraday_ledger"].map(key => root.i18n.catalog[key])
                onSelected: { selectedView = currentIndex; root.controller.selectView(currentIndex) }
                onModelChanged: currentIndex = selectedView
            }
        }
        Label {
            Layout.fillWidth: true; visible: view.selectedView === 0 && root.controller.equitySeries.length > 0
            text: root.i18n.catalog["inner.equity"]; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
        }
        Canvas {
            id: equity; objectName: "intradayInnerEquity"
            Layout.fillWidth: true; Layout.preferredHeight: 54
            visible: view.selectedView === 0 && root.controller.equitySeries.length > 0
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
                    ctx.strokeStyle = ["#9a7427", "#82756d", "#4a8294"][index]; ctx.lineWidth = 2; ctx.beginPath()
                    values.forEach((p, i) => { const x = 42 + (p[0] - xmin) / dx * (width - 50), y = height - 8 - (p[1] - ymin) / dy * (height - 16); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y) })
                    ctx.stroke()
                })
            }
        }
        Components.DataTable {
            objectName: "intradayInnerTable"; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 150
            paged: true; tableModel: root.controller.tableModel; i18n: root.i18n
            cellFormatter: function(value) { return root.i18n.catalog["inner." + value] || root.i18n.catalog["performance." + value] || value }
            onPreviousRequested: root.controller.changePage(-1)
            onNextRequested: root.controller.changePage(1)
        }
    }
}
