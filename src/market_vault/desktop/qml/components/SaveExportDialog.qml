import QtQuick
import QtQuick.Dialogs

FileDialog {
    id: root
    required property var controller
    property string formatName: "csv"
    fileMode: FileDialog.SaveFile
    nameFilters: formatName === "json" ? ["JSON files (*.json)"] : ["CSV files (*.csv)"]
    defaultSuffix: formatName
    onAccepted: controller.exportPage(selectedFile.toString(), formatName)
}
