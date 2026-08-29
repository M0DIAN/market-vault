pragma Singleton
import QtQuick

QtObject {
    readonly property int pixelUnit: 2

    readonly property color canvas: "#EEEAE0"
    readonly property color canvasAlt: "#EBE3D2"
    readonly property color surface: "#F7F1E7"
    readonly property color surfaceRaised: "#FFF9EE"
    readonly property color surfaceMuted: "#E8DDC9"
    readonly property color ink: "#2B2217"
    readonly property color inkMuted: "#6B6257"
    readonly property color inkFaint: "#8A8071"
    readonly property color line: "#B7A98D"
    readonly property color lineSoft: "#D6CBB6"
    readonly property color goldDark: "#725318"
    readonly property color gold: "#B58A2A"
    readonly property color goldMid: "#CDA548"
    readonly property color goldLight: "#E5CB83"
    readonly property color goldHighlight: "#F7E8B1"
    readonly property color goldPale: "#F4E6BC"
    readonly property color vermilion: "#A14A28"
    readonly property color vermilionDark: "#6E2F1D"
    readonly property color success: "#536B49"
    readonly property color warning: "#8B6B2B"
    readonly property color transparent: "transparent"

    readonly property int spacingXs: 4
    readonly property int spacingSm: 8
    readonly property int spacingMd: 12
    readonly property int spacingLg: 18
    readonly property int panelPadding: 12
    readonly property int controlHeight: 34
    readonly property int compactControlHeight: 30
    readonly property int tableHeaderHeight: 30
    readonly property int tableRowHeight: 29
    readonly property int sidebarWidth: 218
    readonly property int statusHeight: 32

    readonly property int fontXs: 10
    readonly property int fontSm: 11
    readonly property int fontMd: 13
    readonly property int fontLg: 17
    readonly property int fontTitle: 21
    readonly property string uiFont: "Fusion Pixel 12px Prop zh_hans"
    readonly property string fallbackUiFont: Qt.platform.os === "windows" ? "Microsoft YaHei UI" : "sans-serif"
    readonly property string dataFont: Qt.platform.os === "windows" ? "Cascadia Mono" : "monospace"
    readonly property string displayFont: uiFont
    readonly property int formFieldWidth: 186
    readonly property int formFieldMinimumWidth: 142

    readonly property int motionFast: 80
    readonly property int motionNormal: 120
    readonly property int motionSlow: 180
    readonly property real disabledOpacity: 0.45
    readonly property real mutedOpacity: 0.72

    function fontForLanguage(language) {
        return uiFont
    }
}
