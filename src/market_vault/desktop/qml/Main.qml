import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components" as Components
import "pages" as Pages

ApplicationWindow {
    id: window
    objectName: "canaryWindow"
    visible: true
    width: 1100
    height: 700
    minimumWidth: 1000
    minimumHeight: 650
    title: i18nBridge.catalog["app.title"]
    color: "#f3eee2"

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 76
            color: "#fffaf0"
            border.color: "#d8c9a6"
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 22
                anchors.rightMargin: 22
                spacing: 16

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1

                    Label {
                        text: i18nBridge.catalog["app.title"]
                        color: "#2b2418"
                        font.pixelSize: 24
                        font.weight: Font.DemiBold
                    }

                    Label {
                        text: i18nBridge.catalog["app.subtitle"]
                        color: "#665d50"
                        font.pixelSize: 13
                    }
                }

                Label {
                    text: i18nBridge.catalog["language.control"]
                    color: "#665d50"
                    font.pixelSize: 12
                }

                Components.LanguageSwitcher {
                    objectName: "languageSwitcher"
                    i18n: i18nBridge
                    Layout.preferredWidth: 120
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Components.Sidebar {
                objectName: "sidebar"
                Layout.preferredWidth: 220
                Layout.fillHeight: true
                shell: shellController
                i18n: i18nBridge
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: "#f3eee2"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: 12

                    Label {
                        id: pageTitle
                        objectName: "pageTitle"
                        text: i18nBridge.catalog[shellController.currentPageLabelKey]
                        color: "#2b2418"
                        font.pixelSize: 22
                        font.weight: Font.DemiBold
                    }

                    Loader {
                        id: pageContent
                        objectName: "pageContent"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        sourceComponent: shellController.currentPage === "home"
                            ? homePageComponent
                            : placeholderPageComponent
                    }
                }
            }
        }
    }

    Component {
        id: homePageComponent

        Pages.HomePage {
            objectName: "homePage"
            dashboard: dashboardController
            desktop: desktopBridge
            i18n: i18nBridge
        }
    }

    Component {
        id: placeholderPageComponent

        Pages.PlaceholderPage {
            pageLabel: i18nBridge.catalog[shellController.currentPageLabelKey]
            message: i18nBridge.catalog["placeholder.message"]
        }
    }
}
