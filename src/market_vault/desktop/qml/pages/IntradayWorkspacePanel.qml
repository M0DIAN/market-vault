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
        }
    }
}
