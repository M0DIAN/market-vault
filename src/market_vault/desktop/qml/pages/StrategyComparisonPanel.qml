import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

ColumnLayout {
    id: root
    objectName: "quantStrategyComparisonPanel"
    required property var controller
    required property var i18n
    property string datasetKey: ""
    property var featureOptions: []
    property var returnOptions: []
    spacing: Theme.PixelTheme.spacingSm

    function syncDataset() {
        const key = root.controller.datasetPath + "|" + (root.controller.datasetSummary.dataset_id || "")
        if (!root.controller.datasetLoaded || key === root.datasetKey)
            return
        root.datasetKey = key
        root.featureOptions = root.controller.featureNames
        root.returnOptions = root.controller.returnLabelNames
        const index = Math.max(0, root.featureOptions.indexOf("return_2"))
        trendFeature.currentIndex = index
        reversionFeature.currentIndex = index
        returnLabel.currentIndex = 0
    }

    Component.onCompleted: syncDataset()
    Connections {
        target: root.controller
        function onResearchChanged() { root.syncDataset() }
    }

    function comparisonValues() {
        return {
            "trend_feature": trendFeature.currentText,
            "trend_threshold": trendThreshold.text,
            "reversion_feature": reversionFeature.currentText,
            "reversion_threshold": reversionThreshold.text,
            "return_label": returnLabel.currentText,
            "ridge_alpha": ridgeAlpha.text,
            "ridge_threshold": ridgeThreshold.text,
            "minimum_train_periods": trainPeriods.text,
            "validation_periods": validationPeriods.text,
            "step_periods": stepPeriods.text,
            "commission_bps": commission.text,
            "slippage_bps": slippage.text
        }
    }

    Components.PixelPanel {
        Layout.fillWidth: true
        Layout.preferredHeight: 222
        padding: Theme.PixelTheme.panelPadding
        GridLayout {
            anchors.fill: parent
            columns: 4
            columnSpacing: Theme.PixelTheme.spacingMd
            rowSpacing: 6
            Components.LabeledComboBox {
                id: trendFeature
                objectName: "quantComparisonTrendFeature"
                label: root.i18n.catalog["quant.trend_feature"]
                model: root.featureOptions
            }
            Components.LabeledTextField {
                id: trendThreshold
                label: root.i18n.catalog["quant.trend_threshold"]
                text: "0"
            }
            Components.LabeledComboBox {
                id: reversionFeature
                objectName: "quantComparisonReversionFeature"
                label: root.i18n.catalog["quant.reversion_feature"]
                model: root.featureOptions
            }
            Components.LabeledTextField {
                id: reversionThreshold
                label: root.i18n.catalog["quant.reversion_threshold"]
                text: "0"
            }
            Components.LabeledComboBox {
                id: returnLabel
                objectName: "quantComparisonReturnLabel"
                label: root.i18n.catalog["quant.return_label"]
                model: root.returnOptions
            }
            Components.LabeledTextField {
                id: ridgeAlpha
                label: root.i18n.catalog["quant.ridge_alpha"]
                text: "1"
            }
            Components.LabeledTextField {
                id: ridgeThreshold
                label: root.i18n.catalog["quant.ridge_threshold"]
                text: "0"
            }
            Components.LabeledTextField {
                id: trainPeriods
                objectName: "quantComparisonTrainPeriods"
                label: root.i18n.catalog["quant.train_periods"]
                text: "20"
            }
            Components.LabeledTextField {
                id: validationPeriods
                objectName: "quantComparisonValidationPeriods"
                label: root.i18n.catalog["quant.validation_periods"]
                text: "5"
            }
            Components.LabeledTextField {
                id: stepPeriods
                objectName: "quantComparisonStepPeriods"
                label: root.i18n.catalog["quant.step_periods"]
                text: "5"
            }
            Components.LabeledTextField {
                id: commission
                label: root.i18n.catalog["quant.commission_bps"]
                text: "0"
            }
            Components.LabeledTextField {
                id: slippage
                label: root.i18n.catalog["quant.slippage_bps"]
                text: "0"
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Components.PixelButton {
            objectName: "quantRunComparisonButton"
            text: root.i18n.catalog["quant.run_comparison"]
            glyph: "chart"
            variant: "primary"
            enabled: root.controller.datasetLoaded
                && root.controller.featureNames.length > 0
                && root.controller.returnLabelNames.length > 0
                && !root.controller.busy && !operationRuntime.busy
            onClicked: root.controller.runStrategyComparison(root.comparisonValues())
        }
        Label {
            Layout.fillWidth: true
            text: root.i18n.catalog["quant.comparison_help"]
            wrapMode: Text.WordWrap
            color: Theme.PixelTheme.inkMuted
            font.pixelSize: Theme.PixelTheme.fontSm
        }
    }
    Components.SummaryStrip {
        Layout.fillWidth: true
        summary: root.controller.comparisonSummary
        i18n: root.i18n
    }
    Components.DataTable {
        objectName: "quantComparisonTable"
        Layout.fillWidth: true
        Layout.fillHeight: true
        tableModel: root.controller.comparisonModel
        i18n: root.i18n
    }
}
