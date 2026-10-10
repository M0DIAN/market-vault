import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradayHistoryPanel"
    required property var controller
    required property var i18n
    function label(key) { return root.i18n.catalog["history." + key] || root.i18n.catalog["inner." + key] || key }
    function sync() {
        candidate.currentIndex = controller.researchController.candidateIndex
        equity.requestPaint()
    }
    Component.onCompleted: sync()
    Connections { target: root.controller; function onChanged() { root.sync() } }
    FileDialog {
        id: dataFile; objectName: "intradayHistoryDataDialog"
        fileMode: FileDialog.OpenFile; nameFilters: ["JSON files (*.json)"]
        onAccepted: root.controller.setDataLocator(selectedFile.toString())
    }
    Dialog {
        id: details; objectName: "intradayHistoryDetailsDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(850, parent.width - 40); height: Math.min(520, parent.height - 40)
        modal: true; title: root.label("details"); standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            clip: true; contentWidth: availableWidth
            Label {
                width: parent.width
                text: {
                    root.i18n.language
                    const values = root.controller.completedDetails
                    return Object.keys(values).map(key => root.label(key) + ": " + values[key]).join("\n")
                }
                wrapMode: Text.WrapAnywhere; color: Theme.PixelTheme.ink
            }
        }
    }
    Dialog {
        id: evidence; objectName: "intradayHistoryEvidenceDialog"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(900, parent.width - 40); height: Math.min(650, parent.height - 40)
        modal: true; title: root.label("page_evidence"); standardButtons: Dialog.Close
        background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
        contentItem: ScrollView {
            objectName: "intradayHistoryEvidenceScroll"
            clip: true; contentWidth: availableWidth
            TextArea {
                objectName: "intradayHistoryEvidenceText"
                width: parent.width; readOnly: true; selectByMouse: true
                text: root.controller.currentPageEvidence
                wrapMode: TextEdit.WrapAnywhere; color: Theme.PixelTheme.ink
            }
        }
    }
    ScrollView {
        id: scroll; objectName: "intradayHistoryScroll"
        anchors.fill: parent; clip: true; contentWidth: availableWidth
        rightPadding: verticalBar.width
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {
            id: verticalBar; objectName: "intradayHistoryScrollBar"
            parent: scroll
            anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.right: parent.right
        }
        ColumnLayout {
            width: scroll.availableWidth; height: Math.max(implicitHeight, scroll.availableHeight)
            spacing: Theme.PixelTheme.spacingSm
            Label {
                objectName: "intradayHistoryMethod"
                Layout.fillWidth: true; text: root.label("method")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledComboBox {
                    id: candidate; objectName: "intradayHistoryCandidate"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("source"); model: root.controller.researchController.candidateNames
                    onSelected: root.controller.researchController.selectCandidate(currentIndex)
                    onModelChanged: currentIndex = root.controller.researchController.candidateIndex
                }
                Components.PixelButton {
                    objectName: "intradayHistoryRunButton"; text: root.label("run")
                    enabled: root.controller.canRun && !operationRuntime.busy
                    onClicked: root.controller.runSelected()
                }
                Components.PixelButton {
                    objectName: "intradayHistoryDetailsButton"; text: root.label("details")
                    enabled: root.controller.resultLoaded; onClicked: details.open()
                }
            }
            Label {
                Layout.fillWidth: true; visible: !root.controller.canRun
                text: root.label("source_required"); wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    id: dataPath; objectName: "intradayHistoryDataPath"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("data"); text: root.controller.dataLocator
                    onTextChanged: root.controller.setDataLocator(text)
                }
                Components.PixelButton {
                    objectName: "intradayHistoryDataBrowse"; text: root.i18n.catalog["quant.browse"]
                    onClicked: dataFile.open()
                }
                Components.PixelButton {
                    objectName: "intradayHistoryDataClear"; text: root.label("clear")
                    onClicked: root.controller.setDataLocator("")
                }
            }
            Label {
                objectName: "intradayHistorySummary"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: {
                    root.i18n.language
                    const result = root.controller.resultSummary
                    if (!result.strategy) return ""
                    return root.label(result.status) + " · " + result.strategy.kind + " · alpha=" + result.strategy.alpha
                        + " · threshold=" + result.strategy.threshold + "\n"
                        + root.label("folds") + ": " + result.fold_count + " · " + root.label("days") + ": " + result.day_count
                        + " · READY: " + result.prediction_count + " · COMPLETE: " + result.complete_target_count
                }
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.ink
            }
            Label {
                objectName: "intradayHistoryNotice"
                Layout.fillWidth: true
                visible: root.controller.draftChanged || root.controller.notice.length > 0 || root.controller.studyError.length > 0
                text: root.controller.studyError ? root.controller.studyError + "\n" + root.label("retry")
                    : root.controller.notice ? root.label(root.controller.notice) : root.label("draft_changed")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledComboBox {
                    id: variant; objectName: "intradayHistoryVariant"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.label("variant")
                    model: ["EXPANDING", "TRAILING_10_DAYS", "TRAILING_20_DAYS", "BENCHMARK"].map(key => root.label(key))
                    currentIndex: root.controller.variantIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.variantIndex)
                    onSelected: root.controller.selectVariant(currentIndex)
                }
                Components.LabeledComboBox {
                    id: view; objectName: "intradayHistoryView"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.intraday_result_view"]
                    model: ["overview", "folds", "keys", "models", "predictions", "trades", "daily", "ledger", "transactions", "fold_contributions"].map(key => root.label(key))
                    currentIndex: root.controller.viewIndex
                    onModelChanged: currentIndex = Qt.binding(() => root.controller.viewIndex)
                    onSelected: root.controller.selectView(currentIndex)
                }
                Components.PixelButton {
                    objectName: "intradayHistoryEvidenceButton"; text: root.label("page_evidence")
                    enabled: root.controller.resultLoaded; onClicked: evidence.open()
                }
            }
            Label {
                objectName: "intradayHistoryVariantNotice"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: {
                    root.i18n.language
                    const result = root.controller.variantSummary
                    if (!result.variant) return ""
                    return root.label(result.variant) + " · " + root.label(result.status)
                        + (result.status === "UNAVAILABLE" ? "\n" + root.label("no_partial_account") : "")
                        + (result.variant === "BENCHMARK" && root.controller.viewIndex > 0 && root.controller.viewIndex < 5
                            ? "\n" + root.label("benchmark_no_model") : "")
                        + (result.unavailable_reasons.length ? "\n" + result.unavailable_reasons.map(row =>
                            root.label("folds") + " " + row.fold_index + ": " + root.label(row.reason)
                            + " (" + row.available_history_days + "/" + row.required_training_days + ")").join("\n") : "")
                }
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted
            }
            Label {
                Layout.fillWidth: true; visible: root.controller.viewIndex === 0 && root.controller.resultLoaded
                text: root.label("economic_note") + "\n" + root.controller.equityNames.map((key, index) =>
                    root.label(key) + " (" + root.label(["gold", "blue", "green", "grey"][index]) + ")").join(" · ")
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradayHistoryReturnBasis"
                Layout.fillWidth: true; visible: root.controller.resultLoaded
                text: {
                    root.i18n.language
                    const basis = root.controller.returnBasis
                    return Object.keys(basis).map(key => root.label(key) + ": " + root.label(basis[key])).join(" · ")
                }
                wrapMode: Text.WordWrap; color: Theme.PixelTheme.inkMuted; font.pixelSize: Theme.PixelTheme.fontSm
            }
            Canvas {
                id: equity; objectName: "intradayHistoryEquity"
                Layout.fillWidth: true; Layout.preferredHeight: 60
                visible: root.controller.viewIndex === 0 && root.controller.resultLoaded
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
                        ctx.strokeStyle = ["#9a7427", "#4a8294", "#53826a", "#82756d"][index]; ctx.lineWidth = 2; ctx.beginPath()
                        values.forEach((p, i) => { const x = 42 + (p[0] - xmin) / dx * (width - 50), y = height - 8 - (p[1] - ymin) / dy * (height - 16); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y) })
                        ctx.stroke()
                    })
                }
            }
            Components.DataTable {
                objectName: "intradayHistoryTable"
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 180
                paged: true; tableModel: root.controller.tableModel; i18n: root.i18n
                cellFormatter: function(value) { return root.i18n.catalog["history." + value]
                    || root.i18n.catalog["prediction_quality." + value] || root.i18n.catalog["inner." + value]
                    || root.i18n.catalog["performance." + value] || root.i18n.catalog["comparison." + value]
                    || root.i18n.catalog["columns." + value] || value }
                onPreviousRequested: root.controller.changePage(-1)
                onNextRequested: root.controller.changePage(1)
            }
        }
    }
}
