import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    required property var controller
    required property var i18n
    property string featureOptionsJson: "[]"

    function syncFeatures() {
        const names = root.controller.intradayFeatureNames
        const encoded = JSON.stringify(names)
        if (encoded === featureOptionsJson) return
        const previous = feature.currentText
        featureOptionsJson = encoded
        feature.model = names
        const selected = names.indexOf(previous)
        feature.currentIndex = selected >= 0 ? selected : Math.max(0, names.indexOf("return_2"))
    }
    function values() {
        return {"signal_field": feature.currentText, "comparator": comparator.currentText,
                "threshold": threshold.text, "commission_bps": commission.text, "slippage_bps": slippage.text,
                "entry_delay_minutes": entryDelay.text, "stop_new_minutes": stopNew.text,
                "flatten_minutes": flatten.text, "max_hold_bars": maxHold.text}
    }
    Component.onCompleted: syncFeatures()
    Connections {
        target: root.controller
        function onResearchChanged() { root.syncFeatures() }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingSm
        Label {
            Layout.fillWidth: true
            text: root.controller.intradayLoaded ? root.controller.intradayPath : root.i18n.catalog["quant.intraday_open_first"]
            color: Theme.PixelTheme.inkMuted
            elide: Text.ElideMiddle
        }
        Components.PixelPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: 210
            padding: Theme.PixelTheme.panelPadding
            GridLayout {
                anchors.fill: parent
                columns: 4
                columnSpacing: Theme.PixelTheme.spacingMd
                rowSpacing: 4
                Components.LabeledComboBox {
                    id: feature
                    objectName: "intradaySignalFeature"
                    label: root.i18n.catalog["quant.signal_feature"]
                    model: []
                }
                Components.LabeledComboBox {
                    id: comparator
                    objectName: "intradayComparator"
                    label: root.i18n.catalog["quant.comparator"]
                    model: ["GT", "GE", "LT", "LE"]
                }
                Components.LabeledTextField {
                    id: threshold
                    objectName: "intradayThreshold"
                    label: root.i18n.catalog["quant.threshold"]
                    text: "0"
                }
                Components.PixelTag { text: "Long / Flat" }
                Components.LabeledTextField {
                    id: commission
                    objectName: "intradayCommission"
                    label: root.i18n.catalog["quant.commission_bps"]
                }
                Components.LabeledTextField {
                    id: slippage
                    objectName: "intradaySlippage"
                    label: root.i18n.catalog["quant.slippage_bps"]
                }
                Components.LabeledTextField {
                    id: entryDelay
                    objectName: "intradayEntryDelay"
                    label: root.i18n.catalog["quant.intraday_entry_delay"]
                    text: "15"
                }
                Components.LabeledTextField {
                    id: stopNew
                    objectName: "intradayStopNew"
                    label: root.i18n.catalog["quant.intraday_stop_new"]
                    text: "30"
                }
                Components.LabeledTextField {
                    id: flatten
                    objectName: "intradayFlatten"
                    label: root.i18n.catalog["quant.intraday_flatten"]
                    text: "5"
                }
                Components.LabeledTextField {
                    id: maxHold
                    objectName: "intradayMaxHold"
                    label: root.i18n.catalog["quant.intraday_max_hold"]
                    text: "12"
                }
                Components.PixelButton {
                    objectName: "intradayRunBacktestButton"
                    text: root.i18n.catalog["quant.run_backtest"]
                    variant: "primary"
                    enabled: root.controller.intradayLoaded && !root.controller.busy && !operationRuntime.busy
                    onClicked: root.controller.runIntradayBacktest(root.values())
                }
                Components.PixelStatusBadge {
                    status: root.controller.status
                    text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) }
                }
            }
        }
        Components.SummaryStrip {
            Layout.fillWidth: true
            summary: root.controller.intradayBacktestSummary
            i18n: root.i18n
        }
        Label {
            Layout.fillWidth: true
            visible: root.controller.intradayBacktestDataId.length > 0
            text: root.i18n.catalog["quant.intraday_result_data"] + ": " + root.controller.intradayBacktestDataId
            color: Theme.PixelTheme.inkMuted
            elide: Text.ElideMiddle
            font.pixelSize: Theme.PixelTheme.fontSm
        }
        RowLayout {
            Repeater {
                model: ["quant.trades", "quant.intraday_ledger", "quant.intraday_daily"]
                Components.PixelButton {
                    required property int index
                    required property string modelData
                    objectName: "intradayView" + index
                    text: root.i18n.catalog[modelData]
                    variant: root.controller.intradayBacktestView === index ? "primary" : "secondary"
                    onClicked: root.controller.selectIntradayBacktestView(index)
                }
            }
        }
        Components.DataTable {
            objectName: "intradayBacktestTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            paged: true
            tableModel: root.controller.intradayBacktestModel
            i18n: root.i18n
            onPreviousRequested: root.controller.changeIntradayBacktestPage(-1)
            onNextRequested: root.controller.changeIntradayBacktestPage(1)
        }
    }
}
