import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme" as Theme

ColumnLayout {
    id: root
    implicitWidth: Theme.PixelTheme.formFieldWidth
    Layout.fillWidth: true
    Layout.minimumWidth: Theme.PixelTheme.formFieldMinimumWidth
    Layout.maximumWidth: Theme.PixelTheme.formFieldWidth

    property alias text: field.text
    property string label: ""
    property string placeholderText: ""
    property string language: "en"
    property int displayYear: 0
    property int displayMonth: 0
    property int selectedYear: -1
    property int selectedMonth: -1
    property int selectedDay: -1
    readonly property bool popupVisible: calendarPopup.visible
    readonly property var calendarLocale: Qt.locale(language === "zh-CN" ? "zh_CN" : "en_US")
    readonly property string monthTitle: new Date(displayYear, displayMonth, 1, 12)
        .toLocaleString(calendarLocale, language === "zh-CN" ? "yyyy年M月" : "MMMM yyyy")

    signal edited(string value)

    spacing: 4

    function parseDate(value) {
        const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
        if (!match)
            return null
        const year = Number(match[1])
        const month = Number(match[2]) - 1
        const day = Number(match[3])
        const parsed = new Date(year, month, day, 12)
        if (parsed.getFullYear() !== year || parsed.getMonth() !== month
                || parsed.getDate() !== day)
            return null
        return parsed
    }

    function canonicalDate(value) {
        const year = value.getFullYear().toString().padStart(4, "0")
        const month = (value.getMonth() + 1).toString().padStart(2, "0")
        const day = value.getDate().toString().padStart(2, "0")
        return year + "-" + month + "-" + day
    }

    function openCalendar() {
        const parsed = parseDate(field.text)
        const initial = parsed || new Date()
        displayYear = initial.getFullYear()
        displayMonth = initial.getMonth()
        selectedYear = parsed ? parsed.getFullYear() : -1
        selectedMonth = parsed ? parsed.getMonth() : -1
        selectedDay = parsed ? parsed.getDate() : -1
        calendarPopup.open()
    }

    function closeCalendar() {
        calendarPopup.close()
    }

    function previousMonth() {
        const previous = new Date(displayYear, displayMonth - 1, 1, 12)
        displayYear = previous.getFullYear()
        displayMonth = previous.getMonth()
    }

    function nextMonth() {
        const next = new Date(displayYear, displayMonth + 1, 1, 12)
        displayYear = next.getFullYear()
        displayMonth = next.getMonth()
    }

    function commitDate(value) {
        const canonical = canonicalDate(value)
        field.text = canonical
        selectedYear = value.getFullYear()
        selectedMonth = value.getMonth()
        selectedDay = value.getDate()
        root.edited(canonical)
        calendarPopup.close()
    }

    Label {
        text: root.label
        color: Theme.PixelTheme.inkMuted
        font.family: Theme.PixelTheme.uiFont
        font.pixelSize: Theme.PixelTheme.fontSm
        elide: Text.ElideRight
        Layout.fillWidth: true
    }

    RowLayout {
        id: dateRow
        Layout.fillWidth: true
        spacing: 4

        PixelTextField {
            id: field
            objectName: root.objectName.length > 0
                ? root.objectName + "Input" : "pixelDateFieldInput"
            Layout.fillWidth: true
            placeholderText: root.placeholderText
            onTextEdited: root.edited(text)
        }

        Button {
            id: calendarTrigger
            objectName: root.objectName.length > 0
                ? root.objectName + "CalendarButton" : "pixelDateFieldCalendarButton"
            Layout.preferredWidth: field.height
            Layout.preferredHeight: field.height
            Layout.alignment: Qt.AlignVCenter
            implicitWidth: field.implicitHeight
            implicitHeight: field.implicitHeight
            padding: 0
            activeFocusOnTab: true
            hoverEnabled: true
            Accessible.name: root.label

            Keys.onPressed: function(event) {
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter
                        || event.key === Qt.Key_Space) {
                    event.accepted = true
                    root.openCalendar()
                }
            }

            background: Item { visible: false }

            contentItem: Item {
                PixelGlyph {
                    objectName: root.objectName.length > 0
                        ? root.objectName + "CalendarGlyph" : "pixelDateFieldCalendarGlyph"
                    anchors.centerIn: parent
                    anchors.horizontalCenterOffset: calendarTrigger.down ? 1 : 0
                    anchors.verticalCenterOffset: calendarTrigger.down ? 1 : 0
                    width: calendarTrigger.width
                    height: calendarTrigger.height
                    glyph: "calendar"
                    pixelUnitOverride: 3
                    color: calendarTrigger.hovered || calendarTrigger.activeFocus
                        || calendarTrigger.down
                        ? Theme.PixelTheme.goldDark : Theme.PixelTheme.inkMuted
                }
            }

            onClicked: root.openCalendar()
        }
    }

    Popup {
        id: calendarPopup
        objectName: root.objectName.length > 0
            ? root.objectName + "CalendarPopup" : "pixelDateFieldCalendarPopup"
        width: 272
        height: 292
        padding: 8
        modal: false
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        x: {
            const window = root.Window.window
            if (!window)
                return 0
            const point = root.mapToItem(window.contentItem, 0, 0)
            const target = Math.max(4, Math.min(point.x, window.width - width - 4))
            return target - point.x
        }
        y: {
            const window = root.Window.window
            if (!window)
                return root.height + 4
            const point = root.mapToItem(window.contentItem, 0, 0)
            const below = point.y + root.height + 4
            return below + height <= window.height - 4 ? root.height + 4 : -height - 4
        }

        background: Item {
            Rectangle {
                anchors.fill: parent
                color: Theme.PixelTheme.goldDark
            }
            Rectangle {
                anchors.fill: parent
                anchors.margins: 2
                color: Theme.PixelTheme.surfaceRaised
            }
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 3
                height: 1
                color: Theme.PixelTheme.goldLight
            }
            Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.top: parent.top }
            Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.top: parent.top }
            Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.left: parent.left; anchors.bottom: parent.bottom }
            Rectangle { width: 2; height: 2; color: Theme.PixelTheme.canvas; anchors.right: parent.right; anchors.bottom: parent.bottom }
        }

        contentItem: ColumnLayout {
            spacing: 5

            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                PixelButton {
                    objectName: root.objectName.length > 0
                        ? root.objectName + "PreviousMonth" : "pixelDateFieldPreviousMonth"
                    Layout.preferredWidth: 30
                    Layout.minimumWidth: 30
                    Layout.maximumWidth: 30
                    implicitWidth: 30
                    compact: true
                    leftPadding: 6
                    rightPadding: 6
                    glyph: "previous"
                    onClicked: root.previousMonth()
                }
                Label {
                    Layout.fillWidth: true
                    text: root.monthTitle
                    color: Theme.PixelTheme.ink
                    font.family: Theme.PixelTheme.uiFont
                    font.pixelSize: Theme.PixelTheme.fontMd
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignHCenter
                }
                PixelButton {
                    objectName: root.objectName.length > 0
                        ? root.objectName + "NextMonth" : "pixelDateFieldNextMonth"
                    Layout.preferredWidth: 30
                    Layout.minimumWidth: 30
                    Layout.maximumWidth: 30
                    implicitWidth: 30
                    compact: true
                    leftPadding: 6
                    rightPadding: 6
                    glyph: "next"
                    onClicked: root.nextMonth()
                }
            }

            DayOfWeekRow {
                Layout.fillWidth: true
                locale: root.calendarLocale
                delegate: Label {
                    required property var model
                    text: model.shortName
                    color: Theme.PixelTheme.inkMuted
                    font.family: Theme.PixelTheme.uiFont
                    font.pixelSize: Theme.PixelTheme.fontSm
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            MonthGrid {
                id: monthGrid
                objectName: root.objectName.length > 0
                    ? root.objectName + "MonthGrid" : "pixelDateFieldMonthGrid"
                Layout.fillWidth: true
                Layout.fillHeight: true
                month: root.displayMonth
                year: root.displayYear
                locale: root.calendarLocale
                onClicked: function(date) { root.commitDate(date) }

                delegate: Rectangle {
                    required property var model
                    readonly property bool inMonth: model.month === monthGrid.month
                    readonly property bool selected: model.year === root.selectedYear
                        && model.month === root.selectedMonth
                        && model.day === root.selectedDay
                    color: selected ? Theme.PixelTheme.goldPale : Theme.PixelTheme.transparent
                    border.color: selected ? Theme.PixelTheme.goldDark
                        : (model.today ? Theme.PixelTheme.gold : Theme.PixelTheme.transparent)
                    border.width: selected ? 2 : (model.today ? 1 : 0)
                    opacity: inMonth ? 1 : 0.18

                    Label {
                        anchors.centerIn: parent
                        text: parent.model.day
                        color: parent.selected ? Theme.PixelTheme.goldDark : Theme.PixelTheme.ink
                        font.family: Theme.PixelTheme.dataFont
                        font.pixelSize: Theme.PixelTheme.fontSm
                    }
                }
            }
        }
    }
}
