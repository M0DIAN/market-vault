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
        RowLayout {
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
        }
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: root.section
            IntradayResearchPanel { controller: root.controller; i18n: root.i18n }
            IntradayBacktestPanel { controller: root.controller; i18n: root.i18n }
            IntradayComparisonPanel { controller: root.controller.intradayResearchController; i18n: root.i18n }
        }
    }
}
