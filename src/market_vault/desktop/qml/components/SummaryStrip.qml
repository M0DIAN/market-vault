import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Flow {
    id: root
    required property var summary
    required property var i18n
    spacing: 8
    Layout.preferredHeight: childrenRect.height
    Repeater {
        model: Object.keys(root.summary)
        Rectangle {
            required property string modelData
            width: summaryLabel.implicitWidth + 18
            height: 30
            color: "#fffaf0"
            border.color: "#d8c9a6"
            Label {
                id: summaryLabel
                anchors.centerIn: parent
                text: {
                    root.i18n.language
                    const localized = root.i18n.catalog["summary." + modelData]
                    return (localized || modelData) + ": " + root.summary[modelData]
                }
                color: "#2b2418"
            }
        }
    }
}
