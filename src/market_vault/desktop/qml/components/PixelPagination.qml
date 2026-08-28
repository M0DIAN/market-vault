import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

RowLayout {
    id: root
    required property var tableModel
    required property var i18n
    signal previousRequested()
    signal nextRequested()
    spacing: Theme.PixelTheme.spacingSm

    PixelButton {
        glyph: "previous"
        compact: true
        variant: "ghost"
        text: root.i18n.catalog["common.previous"]
        enabled: root.tableModel.hasPrevious
        onClicked: root.previousRequested()
    }
    Label {
        text: root.i18n.catalog["common.page"] + " " + root.tableModel.page
            + " " + root.i18n.catalog["common.of"] + " "
            + root.tableModel.totalPages + "  /  " + root.tableModel.totalRows
            + " " + root.i18n.catalog["common.rows"]
        color: Theme.PixelTheme.inkMuted
        font.family: Theme.PixelTheme.displayFont
        font.pixelSize: Theme.PixelTheme.fontSm
    }
    Item { Layout.fillWidth: true }
    PixelButton {
        glyph: "next"
        compact: true
        variant: "ghost"
        text: root.i18n.catalog["common.next"]
        enabled: root.tableModel.hasNext
        onClicked: root.nextRequested()
    }
}
