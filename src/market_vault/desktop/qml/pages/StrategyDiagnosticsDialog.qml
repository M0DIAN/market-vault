import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Dialog {
    id: root
    objectName: "quantDiagnosticsDialog"
    required property var controller
    required property var i18n
    property bool inputAvailable: root.controller.datasetLoaded
    property var submit: function(values) { return root.controller.runStrategyDiagnostics(values) }
    property var comparison: ({})
    property var strategyNames: []
    property var axisOptions: []
    property var axisLabels: []
    property string sourceKey: ""
    property int restoreRevision: -1
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(650, parent ? parent.width - 32 : 650)
    height: Math.max(1, Math.min(implicitHeight, parent ? parent.height - 24 : implicitHeight))
    title: root.i18n.catalog["quant.diagnostics_title"]
    padding: Theme.PixelTheme.panelPadding
    standardButtons: Dialog.NoButton

    function clone(value) { return JSON.parse(JSON.stringify(value)) }
    function selectedStrategy() { return (root.comparison.strategies || [])[strategy.currentIndex] || {} }
    function optionsFor(spec) {
        let options = [{parameter: ""}]
        if (spec.kind === "COMPOSITE_RULE") {
            for (let i = 0; i < spec.conditions.length; ++i)
                options.push({parameter: "condition_threshold", condition_index: i})
        } else {
            options.push({parameter: "threshold"})
            if (spec.kind === "RIDGE") options.push({parameter: "alpha"})
        }
        return options
    }
    function axisLabel(axis) {
        if (!axis.parameter) return root.i18n.catalog["quant.no_axis"]
        if (axis.parameter === "condition_threshold")
            return root.i18n.catalog["quant.condition_axis"] + " " + (axis.condition_index + 1)
        return axis.parameter
    }
    function defaultValue(index) {
        const axis = root.axisOptions[index]
        const spec = selectedStrategy()
        if (!axis || !axis.parameter) return ""
        return String(axis.parameter === "condition_threshold"
            ? spec.conditions[axis.condition_index].threshold : spec[axis.parameter])
    }
    function resetAxes() {
        root.axisOptions = optionsFor(selectedStrategy())
        refreshAxisLabels()
        firstAxis.currentIndex = 1
        secondAxis.currentIndex = 0
        firstValues.text = defaultValue(1)
        secondValues.text = ""
    }
    function refreshAxisLabels() {
        const first = firstAxis.currentIndex, second = secondAxis.currentIndex
        root.axisLabels = root.axisOptions.map(value => root.axisLabel(value))
        firstAxis.currentIndex = first
        secondAxis.currentIndex = second
    }
    Connections {
        target: root.i18n
        function onLanguageChanged() { root.refreshAxisLabels() }
    }
    function loadAxis(combo, field, axis) {
        if (!axis) { combo.currentIndex = 0; field.text = ""; return }
        combo.currentIndex = root.axisOptions.findIndex(value => value.parameter === axis.parameter
            && value.condition_index === axis.condition_index)
        field.text = axis.values.join(",")
    }
    function prepare(values, saved, revision) {
        const key = JSON.stringify(values.strategies)
        const oldName = strategy.currentText
        const restore = revision !== root.restoreRevision
        const changed = key !== root.sourceKey
        root.comparison = clone(values)
        root.strategyNames = values.strategies.map(value => value.name)
        const name = restore && saved.strategy_name ? saved.strategy_name : oldName
        strategy.currentIndex = Math.max(0, root.strategyNames.indexOf(name))
        if (restore || changed || !root.axisOptions.length) {
            resetAxes()
            costs.text = values.commission_bps + "/" + values.slippage_bps
            if (restore && saved.strategy_name === strategy.currentText) {
                loadAxis(firstAxis, firstValues, saved.parameter_axes[0])
                loadAxis(secondAxis, secondValues, saved.parameter_axes[1])
                costs.text = saved.cost_scenarios.map(value => value.commission_bps + "/" + value.slippage_bps).join(",")
            }
        }
        root.sourceKey = key
        root.restoreRevision = revision
        open()
    }
    function axisInput(index, text) {
        if (index <= 0) return null
        return Object.assign({}, root.axisOptions[index], {values: text})
    }
    function values() {
        return {comparison: clone(root.comparison), strategy_name: strategy.currentText,
            parameter_axes: [axisInput(firstAxis.currentIndex, firstValues.text),
                axisInput(secondAxis.currentIndex, secondValues.text)].filter(value => value !== null),
            cost_scenarios: costs.text}
    }
    function count(index, text) { return index <= 0 ? 1 : text.trim() ? text.split(",").length : 0 }
    readonly property int evaluationCount: count(firstAxis.currentIndex, firstValues.text)
        * count(secondAxis.currentIndex, secondValues.text) * (costs.text.trim() ? costs.text.split(",").length : 0)

    background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
    contentItem: ScrollView {
        id: strategyDiagnosticsScroll
        objectName: "strategyDiagnosticsScroll"
        clip: true
        implicitHeight: strategyDiagnosticsContent.implicitHeight
        contentWidth: Math.max(availableWidth, 600)
        contentHeight: strategyDiagnosticsContent.implicitHeight
        ScrollBar.horizontal: Components.PixelScrollBar {}
        ScrollBar.vertical: Components.PixelScrollBar {}

        ColumnLayout {
            id: strategyDiagnosticsContent
            width: strategyDiagnosticsScroll.contentWidth
            spacing: Theme.PixelTheme.spacingMd
            Label {
                Layout.fillWidth: true
                text: root.i18n.catalog["quant.diagnostics_help"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Components.LabeledComboBox {
                id: strategy
                objectName: "quantDiagnosticsStrategy"
                Layout.maximumWidth: 620
                label: root.i18n.catalog["columns.strategy"]
                model: root.strategyNames
                onSelected: root.resetAxes()
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Theme.PixelTheme.spacingMd
                rowSpacing: Theme.PixelTheme.spacingSm
                Components.LabeledComboBox {
                    id: firstAxis
                    objectName: "quantDiagnosticsFirstAxis"
                    Layout.maximumWidth: 290
                    label: root.i18n.catalog["quant.first_axis"]
                    model: root.axisLabels
                    onSelected: firstValues.text = root.defaultValue(currentIndex)
                }
                Components.LabeledTextField {
                    id: firstValues
                    objectName: "quantDiagnosticsFirstValues"
                    Layout.maximumWidth: 290
                    label: root.i18n.catalog["quant.axis_values"]
                    enabled: firstAxis.currentIndex > 0
                }
                Components.LabeledComboBox {
                    id: secondAxis
                    objectName: "quantDiagnosticsSecondAxis"
                    Layout.maximumWidth: 290
                    label: root.i18n.catalog["quant.second_axis"]
                    model: root.axisLabels
                    onSelected: secondValues.text = root.defaultValue(currentIndex)
                }
                Components.LabeledTextField {
                    id: secondValues
                    objectName: "quantDiagnosticsSecondValues"
                    Layout.maximumWidth: 290
                    label: root.i18n.catalog["quant.axis_values"]
                    enabled: secondAxis.currentIndex > 0
                }
            }
            Components.LabeledTextField {
                id: costs
                objectName: "quantDiagnosticsCosts"
                Layout.maximumWidth: 620
                label: root.i18n.catalog["quant.cost_scenarios"]
            }
            Label {
                objectName: "quantDiagnosticsCount"
                Layout.fillWidth: true
                text: root.i18n.catalog["quant.diagnostics_count"] + ": " + root.evaluationCount + " / 64"
                color: Theme.PixelTheme.ink
            }
            Label {
                Layout.fillWidth: true
                visible: root.controller.status === "FAILED" || root.controller.status === "VALIDATION_ERROR"
                text: root.controller.error
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Item { Layout.fillWidth: true }
                Components.PixelButton {
                    objectName: "quantDiagnosticsCancelButton"
                    text: root.i18n.catalog["common.cancel"]
                    onClicked: root.close()
                }
                Components.PixelButton {
                    objectName: "quantDiagnosticsRunButton"
                    text: root.i18n.catalog["quant.run_diagnostics"]
                    variant: "primary"
                    enabled: root.inputAvailable && !root.controller.busy && !operationRuntime.busy
                        && root.evaluationCount > 0 && root.evaluationCount <= 64
                    onClicked: { if (root.submit(root.values())) root.close() }
                }
            }
        }
    }
}
