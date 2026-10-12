import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    required property var controller
    required property var i18n
    property int section: 0
    Connections {
        target: root.controller.intradayProcedureSuiteController
        function onSectionRequested(section) { root.section = section }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.PixelTheme.spacingSm
        Label {
            objectName: "intradayReturnBasisNotice"
            Layout.fillWidth: true
            Layout.minimumHeight: implicitHeight
            text: root.i18n.catalog["quant.return_basis_help"]
            color: Theme.PixelTheme.inkMuted
            font.pixelSize: Theme.PixelTheme.fontSm
            wrapMode: Text.Wrap
        }
        Flow {
            Layout.fillWidth: true
            spacing: Theme.PixelTheme.spacingSm
            Components.PixelButton {
                objectName: "intradayDataTab"
                text: root.i18n.catalog["quant.intraday_data_tab"]
                variant: root.section === 0 ? "primary" : "secondary"
                onClicked: root.section = 0
            }
            Components.PixelButton {
                objectName: "intradayExecutionTab"
                text: root.i18n.catalog["quant.intraday_execution_tab"]
                variant: root.section === 1 ? "primary" : "secondary"
                onClicked: root.section = 1
            }
            Components.PixelButton {
                objectName: "intradayComparisonTab"
                text: root.i18n.catalog["quant.intraday_research_tab"]
                variant: root.section === 2 ? "primary" : "secondary"
                onClicked: root.section = 2
            }
            Components.PixelButton {
                objectName: "intradayFinalTab"
                text: root.i18n.catalog["quant.intraday_final_tab"]
                variant: root.section === 3 ? "primary" : "secondary"
                onClicked: root.section = 3
            }
            Components.PixelButton {
                objectName: "intradaySavedComparisonTab"
                text: root.i18n.catalog["quant.intraday_saved_comparison_tab"]
                variant: root.section === 4 ? "primary" : "secondary"
                onClicked: root.section = 4
            }
            Components.PixelButton {
                objectName: "intradayInnerTab"
                text: root.i18n.catalog["inner.tab"]
                variant: root.section === 5 ? "primary" : "secondary"
                onClicked: root.section = 5
            }
            Components.PixelButton {
                objectName: "intradayHistoryTab"
                text: root.i18n.catalog["history.tab"]
                variant: root.section === 6 ? "primary" : "secondary"
                onClicked: root.section = 6
            }
            Components.PixelButton {
                objectName: "intradayThresholdTab"
                text: root.i18n.catalog["threshold.tab"]
                variant: root.section === 7 ? "primary" : "secondary"
                onClicked: root.section = 7
            }
            Components.PixelButton {
                objectName: "intradayJointTab"
                text: root.i18n.catalog["joint.tab"]
                variant: root.section === 9 ? "primary" : "secondary"
                onClicked: root.section = 9
            }
            Components.PixelButton {
                objectName: "intradayMLDiagnosticsTab"
                text: root.i18n.catalog["ml_diagnostics.tab"]
                variant: root.section === 8 ? "primary" : "secondary"
                onClicked: root.section = 8
            }
            Components.PixelButton {
                objectName: "intradayProcedureTab"
                text: root.i18n.catalog["procedure.tab"]
                variant: root.section === 10 ? "primary" : "secondary"
                onClicked: root.section = 10
            }
            Components.PixelButton {
                objectName: "intradayProcedureStressTab"
                text: root.i18n.catalog["procedure_stress.tab"]
                variant: root.section === 11 ? "primary" : "secondary"
                onClicked: root.section = 11
            }
            Components.PixelButton {
                objectName: "intradaySampleUsageTab"
                text: root.i18n.catalog["sample_usage.tab"]
                variant: root.section === 12 ? "primary" : "secondary"
                onClicked: root.section = 12
            }
            Components.PixelButton {
                objectName: "intradaySuiteTab"
                text: root.i18n.catalog["suite.tab"]
                variant: root.section === 13 ? "primary" : "secondary"
                onClicked: root.section = 13
            }
            Components.PixelButton {
                objectName: "intradaySelectionDiagnosticsTab"
                text: root.i18n.catalog["selection_diagnostics.tab"]
                variant: root.section === 14 ? "primary" : "secondary"
                onClicked: root.section = 14
            }
        }
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.section
            IntradayResearchPanel { controller: root.controller; i18n: root.i18n }
            IntradayBacktestPanel { controller: root.controller; i18n: root.i18n }
            IntradayComparisonPanel { controller: root.controller.intradayResearchController; i18n: root.i18n }
            IntradayFinalPanel { controller: root.controller.intradayFinalController; i18n: root.i18n }
            IntradaySavedComparisonPanel { controller: root.controller.intradaySavedComparisonController; i18n: root.i18n }
            IntradayInnerSelectionPanel { controller: root.controller.intradayInnerSelectionController; i18n: root.i18n }
            IntradayTrainingHistoryPanel { controller: root.controller.intradayTrainingHistoryController; i18n: root.i18n }
            IntradayThresholdSelectionPanel { controller: root.controller.intradayThresholdSelectionController; i18n: root.i18n }
            IntradayMLDiagnosticsPanel { controller: root.controller.intradayMLDiagnosticsController; i18n: root.i18n }
            IntradayThresholdSelectionPanel {
                objectPrefix: "intradayJoint"; translationPrefix: "joint."; jointSelection: true
                controller: root.controller.intradayJointSelectionController; i18n: root.i18n
            }
            IntradayProcedureComparisonPanel { controller: root.controller.intradayProcedureComparisonController; i18n: root.i18n }
            IntradayProcedureStressPanel { controller: root.controller.intradayProcedureStressController; i18n: root.i18n }
            IntradaySampleUsagePanel { controller: root.controller.intradaySampleUsageController; i18n: root.i18n }
            IntradayProcedureSuitePanel { controller: root.controller.intradayProcedureSuiteController; i18n: root.i18n }
            IntradaySelectionDiagnosticsPanel { controller: root.controller.intradaySelectionDiagnosticsController; i18n: root.i18n }
        }
    }
}
