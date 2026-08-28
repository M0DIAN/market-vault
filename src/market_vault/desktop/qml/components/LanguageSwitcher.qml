import QtQuick
import QtQuick.Controls

PixelComboBox {
    id: selector
    required property var i18n
    model: i18n.availableLanguages
    textRole: "label"
    valueRole: "code"
    currentIndex: i18n.language === "zh-CN" ? 0 : 1
    onActivated: i18n.setLanguage(currentValue)
}
