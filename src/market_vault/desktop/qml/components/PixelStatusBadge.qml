import QtQuick
import QtQuick.Controls
import "../theme" as Theme

PixelTag {
    property string status: "IDLE"
    accentColor: status === "FAILED" ? Theme.PixelTheme.vermilion
        : (status === "SUCCESS" || status === "PASS" ? Theme.PixelTheme.success
           : (status === "WARN" || status === "PARTIAL" ? Theme.PixelTheme.warning
              : Theme.PixelTheme.line))
}
