import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Item {
    id: root
    objectName: "intradaySavedComparisonPanel"
    required property var controller
    required property var i18n

    function label(value) {
        return root.i18n.catalog["comparison." + value]
            || root.i18n.catalog["performance." + value]
            || root.i18n.catalog["columns." + value] || value
    }
    FileDialog {
        id: openLeft
        objectName: "intradaySavedOpenLeftDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        title: root.i18n.catalog["quant.saved_open_left"]
        onAccepted: root.controller.openLeft(selectedFile.toString())
    }
    FileDialog {
        id: openRight
        objectName: "intradaySavedOpenRightDialog"
        fileMode: FileDialog.OpenFile
        nameFilters: ["JSON files (*.json)"]
        title: root.i18n.catalog["quant.saved_open_right"]
        onAccepted: root.controller.openRight(selectedFile.toString())
    }
    ScrollView {
        id: scroll
        objectName: "intradaySavedComparisonScroll"
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {}

        ColumnLayout {
            width: scroll.availableWidth
            height: Math.max(implicitHeight, scroll.availableHeight)
            spacing: Theme.PixelTheme.spacingSm
            Label {
                Layout.fillWidth: true
                text: root.i18n.catalog["quant.saved_comparison_help"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Theme.PixelTheme.spacingMd
                enabled: !root.controller.busy && !operationRuntime.busy
                Repeater {
                    model: ["left", "right"]
                    ColumnLayout {
                        id: inputSide
                        required property string modelData
                        readonly property bool isLeft: modelData === "left"
                        readonly property var source: isLeft ? root.controller.leftSource : root.controller.rightSource
                        readonly property string prefix: isLeft ? "intradaySavedLeft" : "intradaySavedRight"
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.alignment: Qt.AlignTop
                        spacing: 4
                        Components.PixelButton {
                            objectName: inputSide.prefix + "Open"
                            text: root.i18n.catalog[inputSide.isLeft ? "quant.saved_open_left" : "quant.saved_open_right"]
                            onClicked: inputSide.isLeft ? openLeft.open() : openRight.open()
                        }
                        Label {
                            objectName: inputSide.prefix + "Path"
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            text: inputSide.source.path || root.i18n.catalog["quant.saved_choose_file"]
                            wrapMode: Text.WrapAnywhere
                            color: Theme.PixelTheme.inkMuted
                            font.pixelSize: Theme.PixelTheme.fontSm
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Components.LabeledComboBox {
                                objectName: inputSide.prefix + "Cost"
                                Layout.fillWidth: true
                                Layout.maximumWidth: Infinity
                                label: root.i18n.catalog["quant.saved_cost_index"]
                                model: inputSide.source.cost_names
                                currentIndex: inputSide.source.cost_index
                                enabled: inputSide.source.loaded && !inputSide.source.is_test
                                onSelected: inputSide.isLeft ? root.controller.selectLeftCost(currentIndex) : root.controller.selectRightCost(currentIndex)
                                // A model reset must preserve updates from later same-shaped file opens.
                                onModelChanged: currentIndex = Qt.binding(() => inputSide.source.cost_index)
                            }
                            Components.LabeledComboBox {
                                objectName: inputSide.prefix + "Candidate"
                                Layout.fillWidth: true
                                Layout.maximumWidth: Infinity
                                label: root.i18n.catalog["quant.saved_candidate_index"]
                                model: inputSide.source.candidate_names
                                currentIndex: inputSide.source.candidate_index
                                enabled: inputSide.source.loaded && !inputSide.source.is_test
                                onSelected: inputSide.isLeft ? root.controller.selectLeftCandidate(currentIndex) : root.controller.selectRightCandidate(currentIndex)
                                onModelChanged: currentIndex = Qt.binding(() => inputSide.source.candidate_index)
                            }
                        }
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Components.PixelButton {
                    objectName: "intradaySavedCompareButton"
                    text: root.i18n.catalog["quant.saved_compare"]
                    variant: "primary"
                    enabled: root.controller.canCompare && !root.controller.busy && !operationRuntime.busy
                    onClicked: root.controller.compare()
                }
                Item { Layout.fillWidth: true }
                Components.PixelStatusBadge {
                    status: root.controller.status
                    text: { root.i18n.language; return root.i18n.statusLabel(root.controller.status) }
                }
            }
            Label {
                objectName: "intradaySavedComparisonError"
                textFormat: Text.PlainText
                Layout.fillWidth: true
                visible: text.length > 0
                text: root.controller.error
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                Layout.fillWidth: true
                visible: root.controller.resultLoaded
                text: root.i18n.catalog["quant.saved_bound_sources"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Theme.PixelTheme.spacingMd
                visible: root.controller.resultLoaded
                Repeater {
                    model: root.controller.boundSources
                    ColumnLayout {
                        id: boundSide
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        Layout.alignment: Qt.AlignTop
                        spacing: 4
                        Label {
                            objectName: "intradaySavedBound" + boundSide.modelData.side + "Selection"
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            text: boundSide.modelData.side + " · " + (boundSide.modelData.name || root.i18n.catalog["comparison.unnamed"])
                                + "\n" + root.label(boundSide.modelData.evaluation_mode) + " · "
                                + root.i18n.catalog["quant.saved_cost_index"] + " " + boundSide.modelData.cost_index + " · "
                                + root.i18n.catalog["quant.saved_candidate_index"] + " " + boundSide.modelData.candidate_index
                                + " · " + boundSide.modelData.strategy.name
                            wrapMode: Text.WrapAnywhere
                            color: Theme.PixelTheme.ink
                            font.pixelSize: Theme.PixelTheme.fontSm
                        }
                        Label {
                            objectName: "intradaySavedBound" + boundSide.modelData.side + "Identity"
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            text: boundSide.modelData.path + "\n"
                                + root.i18n.catalog["quant.saved_experiment_id"] + ": " + boundSide.modelData.experiment_id + "\n"
                                + root.i18n.catalog["quant.saved_candidate_id"] + ": " + boundSide.modelData.candidate_id + "\n"
                                + root.i18n.catalog["quant.saved_data_id"] + ": " + boundSide.modelData.data_id
                            wrapMode: Text.WrapAnywhere
                            color: Theme.PixelTheme.inkMuted
                            font.pixelSize: Theme.PixelTheme.fontSm
                        }
                    }
                }
            }
            Label {
                objectName: "intradaySavedComparisonNotice"
                Layout.fillWidth: true
                visible: root.controller.resultLoaded
                text: root.i18n.catalog["quant.saved_notice_" + root.controller.comparisonNotice] || root.label(root.controller.comparisonNotice)
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                Layout.fillWidth: true
                visible: root.controller.resultLoaded
                text: root.i18n.catalog["quant.saved_evidence_note"] + "\n" + root.i18n.catalog["quant.saved_units_note"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Repeater {
                model: root.controller.performanceWarnings
                Label {
                    required property var modelData
                    objectName: "intradaySavedWarning" + modelData.side + modelData.part
                    textFormat: Text.PlainText
                    Layout.fillWidth: true
                    text: modelData.side + " · " + root.label(modelData.part) + " · " + root.label(modelData.reason)
                        + (modelData.detail ? "\n" + modelData.detail : "")
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
            Components.LabeledComboBox {
                objectName: "intradaySavedComparisonView"
                Layout.fillWidth: true
                Layout.maximumWidth: 300
                label: root.i18n.catalog["quant.intraday_result_view"]
                model: ["quant.saved_strategy_metrics", "quant.saved_benchmark_metrics", "quant.saved_config_differences", "quant.saved_basis_checks"].map(key => root.i18n.catalog[key])
                currentIndex: root.controller.viewIndex
                onSelected: root.controller.selectView(currentIndex)
                onModelChanged: currentIndex = Qt.binding(() => root.controller.viewIndex)
            }
            Label {
                Layout.fillWidth: true
                visible: root.controller.viewIndex === 3
                text: root.i18n.catalog["quant.saved_compact_values"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            ColumnLayout {
                objectName: "intradaySavedConfigurationDifferences"
                Layout.fillWidth: true
                visible: root.controller.viewIndex === 2
                Label {
                    Layout.fillWidth: true
                    visible: root.controller.resultLoaded && root.controller.configurationRows.length === 0
                    text: root.i18n.catalog["quant.saved_no_differences"]
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
                Repeater {
                    model: root.controller.configurationRows
                    ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Label {
                            Layout.fillWidth: true
                            text: root.label(modelData.key)
                            wrapMode: Text.WordWrap
                            color: Theme.PixelTheme.ink
                            font.pixelSize: Theme.PixelTheme.fontSm
                        }
                        Label {
                            Layout.fillWidth: true
                            textFormat: Text.PlainText
                            text: "A: " + root.label(modelData.left) + "\nB: " + root.label(modelData.right)
                            wrapMode: Text.WrapAnywhere
                            color: Theme.PixelTheme.inkMuted
                            font.pixelSize: Theme.PixelTheme.fontSm
                        }
                    }
                }
            }
            Components.DataTable {
                objectName: "intradaySavedComparisonTable"
                visible: root.controller.viewIndex !== 2
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 220
                paged: true
                tableModel: root.controller.tableModel
                i18n: root.i18n
                cellFormatter: function(value) { return root.label(value) }
                onPreviousRequested: root.controller.changePage(-1)
                onNextRequested: root.controller.changePage(1)
            }
        }
    }
}
