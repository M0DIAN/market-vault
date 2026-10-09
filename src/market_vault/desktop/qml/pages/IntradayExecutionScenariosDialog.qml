import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Dialog {
    id: root
    objectName: "intradayExecutionScenariosDialog"
    required property var controller
    required property var i18n
    property var comparison: ({})
    property var scenarios: []
    property int activeIndex: -1
    property string sourceKey: ""
    property int restoreRevision: -1
    readonly property int evaluationCount: scenarios.length * (comparison.strategies || []).length
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(760, parent ? parent.width - 32 : 760)
    height: Math.max(1, Math.min(implicitHeight, parent ? parent.height - 24 : implicitHeight))
    title: root.i18n.catalog["quant.execution_scenarios"]
    padding: Theme.PixelTheme.panelPadding
    standardButtons: Dialog.NoButton

    function clone(value) { return JSON.parse(JSON.stringify(value)) }
    function policyFrom(values) {
        const policy = {}
        for (const key of ["entry_delay_minutes", "stop_new_minutes", "flatten_minutes", "max_hold_bars", "commission_bps", "slippage_bps"])
            policy[key] = values[key] === undefined || values[key] === null ? "" : String(values[key])
        return policy
    }
    function commit() {
        if (root.activeIndex < 0 || root.activeIndex >= root.scenarios.length) return
        const values = root.clone(root.scenarios)
        values[root.activeIndex] = {name: scenarioName.text, execution: {
            entry_delay_minutes: entryDelay.text, stop_new_minutes: stopNew.text,
            flatten_minutes: flatten.text, max_hold_bars: maxHold.text,
            commission_bps: commission.text, slippage_bps: slippage.text}}
        root.scenarios = values
    }
    function load(index) {
        root.activeIndex = index
        const value = root.scenarios[index]
        scenarioName.text = value.name
        const policy = root.policyFrom(value.execution)
        entryDelay.text = policy.entry_delay_minutes
        stopNew.text = policy.stop_new_minutes
        flatten.text = policy.flatten_minutes
        maxHold.text = policy.max_hold_bars
        commission.text = policy.commission_bps
        slippage.text = policy.slippage_bps
        selected.currentIndex = index
    }
    function prepare(values, saved, revision) {
        root.commit()
        root.comparison = root.clone(values)
        if (!root.scenarios.length || root.sourceKey !== values.data_id || root.restoreRevision !== revision) {
            root.activeIndex = -1
            root.scenarios = saved.execution_scenarios && root.restoreRevision !== revision
                ? root.clone(saved.execution_scenarios)
                : [{name: root.i18n.catalog["quant.scenario_name_prefix"] + " 1", execution: root.policyFrom(values)}]
            root.load(0)
        }
        root.sourceKey = values.data_id
        root.restoreRevision = revision
        root.open()
    }
    function add() {
        root.commit()
        const values = root.clone(root.scenarios)
        let number = values.length + 1
        const prefix = root.i18n.catalog["quant.scenario_name_prefix"] + " "
        while (values.some(value => value.name === prefix + number)) ++number
        values.push({name: prefix + number, execution: root.clone(values[root.activeIndex].execution)})
        root.scenarios = values
        root.load(values.length - 1)
    }
    function remove() {
        if (root.scenarios.length <= 1) return
        const values = root.clone(root.scenarios)
        values.splice(root.activeIndex, 1)
        const index = Math.min(root.activeIndex, values.length - 1)
        root.activeIndex = -1
        root.scenarios = values
        root.load(index)
    }
    function run() {
        root.commit()
        if (root.controller.runScenarios({comparison: root.clone(root.comparison), execution_scenarios: root.clone(root.scenarios)}))
            root.close()
    }
    onClosed: root.commit()

    background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
    contentItem: ScrollView {
        id: scroll
        objectName: "intradayScenariosEditorScroll"
        clip: true
        implicitHeight: content.implicitHeight
        contentWidth: availableWidth
        contentHeight: content.implicitHeight
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical: Components.PixelScrollBar {}

        ColumnLayout {
            id: content
            width: scroll.availableWidth
            spacing: Theme.PixelTheme.spacingSm
            Label {
                Layout.fillWidth: true
                text: root.i18n.catalog["quant.scenarios_editor_help"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Components.LabeledComboBox {
                    id: selected
                    objectName: "intradayScenarioEditorChoice"
                    Layout.fillWidth: true
                    Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.execution_scenario"]
                    model: root.scenarios.map(value => value.name)
                    onSelected: { const index = currentIndex; root.commit(); root.load(index) }
                    onModelChanged: currentIndex = root.activeIndex
                }
                Components.PixelButton {
                    objectName: "intradayScenarioAdd"
                    text: root.i18n.catalog["quant.scenario_add"]
                    enabled: (root.scenarios.length + 1) * (root.comparison.strategies || []).length <= 64
                    onClicked: root.add()
                }
                Components.PixelButton {
                    objectName: "intradayScenarioRemove"
                    text: root.i18n.catalog["quant.scenario_remove"]
                    enabled: root.scenarios.length > 1
                    onClicked: root.remove()
                }
            }
            Components.LabeledTextField {
                id: scenarioName
                objectName: "intradayScenarioName"
                Layout.fillWidth: true
                Layout.maximumWidth: Infinity
                label: root.i18n.catalog["quant.scenario_name"]
            }
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: Theme.PixelTheme.spacingMd
                rowSpacing: Theme.PixelTheme.spacingSm
                Components.LabeledTextField {
                    id: entryDelay; objectName: "intradayScenarioEntryDelay"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.intraday_entry_delay"]
                }
                Components.LabeledTextField {
                    id: stopNew; objectName: "intradayScenarioStopNew"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.intraday_stop_new"]
                }
                Components.LabeledTextField {
                    id: flatten; objectName: "intradayScenarioFlatten"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.intraday_flatten"]
                }
                Components.LabeledTextField {
                    id: maxHold; objectName: "intradayScenarioMaxHold"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.intraday_max_hold"]
                }
                Components.LabeledTextField {
                    id: commission; objectName: "intradayScenarioCommission"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.commission_bps"]
                }
                Components.LabeledTextField {
                    id: slippage; objectName: "intradayScenarioSlippage"
                    Layout.fillWidth: true; Layout.maximumWidth: Infinity
                    label: root.i18n.catalog["quant.slippage_bps"]
                }
            }
            Label {
                objectName: "intradayScenariosEvaluationCount"
                Layout.fillWidth: true
                text: root.scenarios.length + " × " + (root.comparison.strategies || []).length + " = "
                    + root.evaluationCount + " · " + root.i18n.catalog["quant.scenarios_evaluation_limit"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                Layout.fillWidth: true
                visible: root.controller.error.length > 0
                text: root.controller.error
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
        }
    }
    footer: RowLayout {
        spacing: Theme.PixelTheme.spacingSm
        Item { Layout.fillWidth: true }
        Components.PixelButton {
            objectName: "intradayScenariosKeep"
            text: root.i18n.catalog["quant.intraday_apply_settings"]
            onClicked: root.close()
        }
        Components.PixelButton {
            objectName: "intradayScenariosRun"
            text: root.i18n.catalog["quant.scenarios_run"]
            variant: "primary"
            enabled: root.controller.dataLoaded && !root.controller.busy && !operationRuntime.busy
                && root.evaluationCount > 0 && root.evaluationCount <= 64
            onClicked: root.run()
        }
    }
}
