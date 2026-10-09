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
    property bool showPortfolioDates: false
    property bool showPortfolioPolicies: false

    function label(value) {
        return (root.controller.portfolioView && root.i18n.catalog["portfolio." + value])
            || root.i18n.catalog["comparison." + value]
            || root.i18n.catalog["performance." + value]
            || root.i18n.catalog["columns." + value] || value
    }
    function available(value) { return value === undefined || value === null ? "—" : value }
    function weight(value) { return value === undefined || value === null ? "—" : (100 * value).toLocaleString(Qt.locale(root.i18n.language), "g", 6) + "%" }
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
            Label {
                Layout.fillWidth: true
                text: root.i18n.catalog["portfolio.draft_note"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledTextField {
                    objectName: "intradayPortfolioWeightA"
                    Layout.minimumWidth: 140
                    Layout.maximumWidth: 220
                    label: root.i18n.catalog["portfolio.weight_a"]
                    text: root.controller.weightAText
                    onEdited: function(value) { root.controller.setWeightA(value) }
                }
                Components.LabeledTextField {
                    objectName: "intradayPortfolioWeightB"
                    Layout.minimumWidth: 140
                    Layout.maximumWidth: 220
                    label: root.i18n.catalog["portfolio.weight_b"]
                    text: root.controller.weightBText
                    onEdited: function(value) { root.controller.setWeightB(value) }
                }
                Label {
                    objectName: "intradayPortfolioDraftCash"
                    Layout.fillWidth: true
                    text: root.i18n.catalog["portfolio.draft_cash"] + ": " + root.controller.draftCashWeight
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
            Label {
                objectName: "intradayPortfolioInputReason"
                Layout.fillWidth: true
                visible: root.controller.portfolioInputReason.length > 0
                text: root.i18n.catalog["portfolio." + root.controller.portfolioInputReason] || ""
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
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
                Components.PixelButton {
                    objectName: "intradayPortfolioAnalyzeButton"
                    text: root.i18n.catalog["portfolio.analyze"]
                    enabled: root.controller.canAnalyzePortfolio && !root.controller.busy && !operationRuntime.busy
                    onClicked: root.controller.analyzePortfolio()
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
                visible: root.controller.displayedResultLoaded
                text: root.i18n.catalog[root.controller.portfolioView ? "portfolio.bound_sources" : "quant.saved_bound_sources"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Theme.PixelTheme.spacingMd
                visible: root.controller.displayedResultLoaded
                Repeater {
                    model: root.controller.displayedBoundSources
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
                                + (root.controller.portfolioView ? "\n" + root.i18n.catalog["portfolio.source_days"] + ": "
                                    + root.available((boundSide.modelData.sample || ({})).sample_count) + " · "
                                    + root.available((boundSide.modelData.sample || ({})).first_day) + " → "
                                    + root.available((boundSide.modelData.sample || ({})).last_day) : "")
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
                objectName: "intradayPortfolioBoundAllocation"
                Layout.fillWidth: true
                visible: root.controller.portfolioView && root.controller.portfolioResultLoaded
                text: {
                    let allocation = root.controller.portfolioContext.allocation || ({})
                    return root.i18n.catalog["portfolio.bound_weights"] + ": A " + root.weight(allocation.weight_a)
                        + " · B " + root.weight(allocation.weight_b) + " · " + root.i18n.catalog["portfolio.CASH"] + " " + root.weight(allocation.cash_weight)
                        + "\n" + root.i18n.catalog["portfolio.capital_note"]
                }
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradaySavedComparisonNotice"
                Layout.fillWidth: true
                visible: !root.controller.portfolioView && root.controller.resultLoaded
                text: root.i18n.catalog["quant.saved_notice_" + root.controller.comparisonNotice] || root.label(root.controller.comparisonNotice)
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                Layout.fillWidth: true
                visible: !root.controller.portfolioView && root.controller.resultLoaded
                text: root.i18n.catalog["quant.saved_evidence_note"] + "\n" + root.i18n.catalog["quant.saved_units_note"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Repeater {
                model: root.controller.portfolioView ? [] : root.controller.performanceWarnings
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
            Label {
                objectName: "intradayPortfolioNotice"
                Layout.fillWidth: true
                visible: root.controller.portfolioView && root.controller.portfolioResultLoaded
                text: {
                    let context = root.controller.portfolioContext
                    let availability = context.availability || ({})
                    let basis = context.basis || ({})
                    let failures = (basis.failed_checks || []).map(value => root.label(value)).join(" · ")
                    return root.label(availability.status || "")
                        + (availability.unavailable_reason ? " · " + root.label(availability.unavailable_reason) : "")
                        + (failures ? "\n" + root.i18n.catalog["portfolio.failed_basis"] + ": " + failures : "")
                        + (availability.detail ? "\n" + availability.detail : "")
                }
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Repeater {
                model: root.controller.portfolioView ? root.controller.portfolioWarnings : []
                Label {
                    required property var modelData
                    objectName: "intradayPortfolioWarning" + modelData.side + modelData.part
                    textFormat: Text.PlainText
                    Layout.fillWidth: true
                    text: modelData.side + " · " + root.label(modelData.part) + " · " + root.label(modelData.reason)
                        + (modelData.detail ? "\n" + modelData.detail : "")
                    wrapMode: Text.WordWrap
                    color: Theme.PixelTheme.ink
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
            }
            Label {
                objectName: "intradayPortfolioSample"
                Layout.fillWidth: true
                visible: root.controller.portfolioView && root.controller.portfolioResultLoaded
                text: {
                    let sample = root.controller.portfolioContext.sample || ({})
                    return root.i18n.catalog["portfolio.sample"] + ": " + root.available(sample.sample_count)
                        + " · " + root.available(sample.first_day) + " → " + root.available(sample.last_day)
                        + "\n" + root.i18n.catalog["portfolio.session_minutes"] + ": " + root.available(sample.total_session_minutes)
                        + " · " + root.i18n.catalog["portfolio.folds"] + ": " + root.available(sample.fold_count)
                        + " · " + root.i18n.catalog["portfolio.unevaluated"] + ": " + root.available(sample.unevaluated_development_day_count)
                        + (sample.unavailable_reason ? " · " + root.label(sample.unavailable_reason) : "")
                }
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.LabeledComboBox {
                objectName: "intradaySavedComparisonView"
                Layout.fillWidth: true
                Layout.maximumWidth: 300
                label: root.i18n.catalog["quant.intraday_result_view"]
                model: ["quant.saved_strategy_metrics", "quant.saved_benchmark_metrics", "quant.saved_config_differences", "quant.saved_basis_checks",
                    "portfolio.complementarity", "portfolio.summary", "portfolio.path", "portfolio.attribution"].map(key => root.i18n.catalog[key])
                currentIndex: root.controller.viewIndex
                onSelected: root.controller.selectView(currentIndex)
                onModelChanged: currentIndex = Qt.binding(() => root.controller.viewIndex)
            }
            Label {
                objectName: "intradayPortfolioViewNote"
                Layout.fillWidth: true
                visible: root.controller.portfolioView
                text: root.i18n.catalog[["portfolio.complementarity_note", "portfolio.summary_note", "portfolio.path_note", "portfolio.attribution_note"][root.controller.viewIndex - 4]] || ""
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.PixelButton {
                objectName: "intradayPortfolioDatesButton"
                visible: root.controller.viewIndex === 4 && root.controller.portfolioResultLoaded
                    && root.controller.portfolioJointLossDays.length > 0
                text: root.i18n.catalog["portfolio.loss_dates"]
                onClicked: root.showPortfolioDates = !root.showPortfolioDates
            }
            Label {
                objectName: "intradayPortfolioLossDates"
                Layout.fillWidth: true
                visible: root.controller.viewIndex === 4 && root.showPortfolioDates
                text: root.controller.portfolioJointLossDays.join(" · ")
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.PixelButton {
                objectName: "intradayPortfolioPoliciesButton"
                visible: root.controller.viewIndex === 7 && root.controller.portfolioResultLoaded
                text: root.i18n.catalog["portfolio.source_policies"]
                onClicked: root.showPortfolioPolicies = !root.showPortfolioPolicies
            }
            ColumnLayout {
                objectName: "intradayPortfolioPolicies"
                Layout.fillWidth: true
                visible: root.controller.viewIndex === 7 && root.showPortfolioPolicies
                Repeater {
                    model: root.controller.portfolioPolicyRows
                    Label {
                        required property var modelData
                        objectName: "intradayPortfolioPolicy" + modelData.side + modelData.account
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: modelData.side + " · " + root.label(modelData.account) + "\n"
                            + modelData.fields.map(field => root.label(field.key) + ": " + field.value).join(" · ")
                        wrapMode: Text.WordWrap
                        color: Theme.PixelTheme.inkMuted
                        font.pixelSize: Theme.PixelTheme.fontSm
                    }
                }
                Repeater {
                    model: root.controller.portfolioView ? root.controller.displayedBoundSources : []
                    Label {
                        required property var modelData
                        objectName: "intradayPortfolioProvenance" + modelData.side
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: modelData.side + " · " + root.i18n.catalog["comparison.feature_fields"] + ": " + JSON.stringify(modelData.feature_fields)
                            + "\n" + root.i18n.catalog["portfolio.strategy_execution_id"] + ": " + modelData.strategy_execution_id
                            + "\n" + root.i18n.catalog["portfolio.benchmark_execution_id"] + ": " + modelData.benchmark_execution_id
                        wrapMode: Text.WrapAnywhere
                        color: Theme.PixelTheme.inkMuted
                        font.pixelSize: Theme.PixelTheme.fontSm
                    }
                }
                Label {
                    objectName: "intradayPortfolioReportId"
                    Layout.fillWidth: true
                    text: root.i18n.catalog["portfolio.report_id"] + ": " + (root.controller.portfolioContext.portfolio_id || "")
                    wrapMode: Text.WrapAnywhere
                    color: Theme.PixelTheme.inkMuted
                    font.pixelSize: Theme.PixelTheme.fontSm
                }
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
