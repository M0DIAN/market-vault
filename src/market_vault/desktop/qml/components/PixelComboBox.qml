import QtQuick
import QtQuick.Controls
import "../theme" as Theme

ComboBox {
    id: control
    implicitHeight: Theme.PixelTheme.controlHeight
    leftPadding: 10
    rightPadding: 28
    activeFocusOnTab: true
    font.family: Theme.PixelTheme.uiFont
    font.pixelSize: Theme.PixelTheme.fontMd
    opacity: enabled ? 1 : Theme.PixelTheme.disabledOpacity

    contentItem: Text {
        leftPadding: 0
        rightPadding: 0
        text: control.displayText
        font: control.font
        color: Theme.PixelTheme.ink
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    indicator: PixelGlyph {
        x: control.width - width - 8
        y: Math.round((control.height - height) / 2)
        width: 14
        height: 14
        glyph: "next"
        rotation: 90
        color: Theme.PixelTheme.goldDark
    }
    background: Item {
        Rectangle { anchors.fill: parent; color: control.activeFocus ? Theme.PixelTheme.goldDark : Theme.PixelTheme.line }
        Rectangle { anchors.fill: parent; anchors.margins: control.activeFocus ? 3 : 1; color: Theme.PixelTheme.surfaceRaised }
        Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: control.activeFocus ? 4 : 2; height: 1; color: Theme.PixelTheme.goldLight }
        Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: control.activeFocus ? 4 : 2; height: 1; color: Theme.PixelTheme.goldDark }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.top: parent.top }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.top: parent.top }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.bottom: parent.bottom }
        Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.bottom: parent.bottom }
    }
    popup: Popup {
        y: control.height
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 2, 260)
        padding: 1
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
        background: Rectangle {
            color: Theme.PixelTheme.surfaceRaised
            border.color: Theme.PixelTheme.goldDark
            border.width: 1
        }
    }
    delegate: ItemDelegate {
        required property var model
        width: control.width - 2
        height: Theme.PixelTheme.compactControlHeight
        contentItem: Text {
            text: model[control.textRole]
            color: Theme.PixelTheme.ink
            font: control.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            color: highlighted ? Theme.PixelTheme.goldPale : Theme.PixelTheme.surfaceRaised
        }
    }
}
