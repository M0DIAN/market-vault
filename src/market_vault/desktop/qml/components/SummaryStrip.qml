import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

Flow {
    id: root
    required property var summary
    required property var i18n
    spacing: Theme.PixelTheme.spacingSm
    Layout.preferredHeight: childrenRect.height
    Repeater {
        model: Object.keys(root.summary)
        PixelTag {
            required property string modelData
            text: {
                root.i18n.language
                const localized = root.i18n.catalog["summary." + modelData]
                return (localized || modelData) + ": " + root.summary[modelData]
            }
        }
    }
}
