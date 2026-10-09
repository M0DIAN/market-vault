import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

Dialog {
    id: root
    objectName: "intradayResearchSettings"
    required property var i18n
    property var availableFeatures: []
    property string availableDataId: ""
    property string dataId: ""
    property string dataLocator: ""
    property bool executionPolicyBound: false
    property var savePlan: null
    property string errorText: ""
    readonly property var featureOptions: {
        const names = root.dataId === root.availableDataId ? root.availableFeatures.slice() : []
        const keep = function(name) { if (name && names.indexOf(name) < 0) names.push(name) }
        features.text.split(",").forEach(name => keep(name.trim()))
        editor.strategies.forEach(spec => {
            if (spec.kind === "FEATURE_RULE") keep(spec.signal_field)
            for (const rule of (spec.conditions || [])) keep(rule.signal_field)
        })
        editor.conditionDraft.forEach(rule => keep(rule.signal_field))
        return names
    }
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(960, parent ? parent.width - 32 : 960)
    height: Math.max(1, Math.min(implicitHeight, parent ? parent.height - 24 : implicitHeight))
    title: root.i18n.catalog["quant.intraday_settings"]
    padding: Theme.PixelTheme.panelPadding
    standardButtons: Dialog.NoButton

    function applySource(sourceId, names, plan, locator) {
        root.availableFeatures = names
        root.availableDataId = sourceId
        if (root.dataId === sourceId) return
        root.dataId = sourceId
        root.dataLocator = locator || ""
        root.executionPolicyBound = false
        if (plan.strategies) {
            applyPlan(plan, false)
        } else {
            // A short source can support a manual split even when the default
            // percentages cannot propose three nonempty day groups.
            features.text = names.indexOf("return_2") >= 0 ? "return_2" : (names[0] || "")
            editor.reset(features.text)
            trainEnd.text = ""; valEnd.text = ""; testEnd.text = ""
            trainDays.text = "20"; valDays.text = "5"; stepDays.text = "5"
        }
    }

    function applyPlan(plan, restoreCosts) {
        if (!plan.strategies) return
        root.dataId = plan.data_id
        root.dataLocator = plan.intraday_data_path
        root.executionPolicyBound = restoreCosts
        features.text = plan.feature_fields.join(",")
        trainEnd.text = plan.split.train_end_day
        valEnd.text = plan.split.validation_end_day
        testEnd.text = plan.split.test_end_day
        trainDays.text = String(plan.walk_forward.minimum_train_days)
        valDays.text = String(plan.walk_forward.validation_days)
        stepDays.text = String(plan.walk_forward.step_days)
        entryDelay.text = String(plan.execution.entry_delay_minutes)
        stopNew.text = String(plan.execution.stop_new_minutes)
        flatten.text = String(plan.execution.flatten_minutes)
        maxHold.text = String(plan.execution.max_hold_bars)
        if (restoreCosts) {
            commission.text = String(plan.execution.commission_bps)
            slippage.text = String(plan.execution.slippage_bps)
        }
        editor.strategies = editor.clone(plan.strategies)
        editor.load(0)
    }
    function values() {
        return {data_id: root.dataId, intraday_data_path: root.dataLocator, execution_policy_bound: root.executionPolicyBound,
            feature_fields: features.text.split(",").map(value => value.trim()), strategies: editor.snapshot(),
            train_end_day: trainEnd.text, validation_end_day: valEnd.text, test_end_day: testEnd.text,
            minimum_train_days: trainDays.text, validation_days: valDays.text, step_days: stepDays.text,
            commission_bps: commission.text, slippage_bps: slippage.text, entry_delay_minutes: entryDelay.text,
            stop_new_minutes: stopNew.text, flatten_minutes: flatten.text, max_hold_bars: maxHold.text}
    }
    readonly property string summary: "TRAIN ≤ " + trainEnd.text + " | VALIDATION ≤ " + valEnd.text
        + " | TEST ≤ " + testEnd.text + "\nWF: " + trainDays.text + "/" + valDays.text + "/" + stepDays.text
        + " | " + root.i18n.catalog["quant.commission_bps"] + ": " + (commission.text || "—")
        + " | " + root.i18n.catalog["quant.slippage_bps"] + ": " + (slippage.text || "—")

    background: Rectangle { color: Theme.PixelTheme.surface; border.color: Theme.PixelTheme.goldDark }
    contentItem: ScrollView {
        id: intradaySettingsScroll
        objectName: "intradaySettingsScroll"
        clip: true
        implicitHeight: intradaySettingsContent.implicitHeight
        contentWidth: Math.max(availableWidth, 880)
        contentHeight: intradaySettingsContent.implicitHeight
        ScrollBar.horizontal: Components.PixelScrollBar {}
        ScrollBar.vertical: Components.PixelScrollBar {}

        ColumnLayout {
            id: intradaySettingsContent
            width: intradaySettingsScroll.contentWidth
            spacing: Theme.PixelTheme.spacingSm
            Label {
                Layout.fillWidth: true
                text: root.i18n.catalog["quant.intraday_research_help"]
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            Label {
                objectName: "intradayPlanLocator"
                Layout.fillWidth: true
                text: root.i18n.catalog["plan.locator"] + ": " + root.dataLocator + "\nData ID: " + root.dataId + "\n"
                    + root.i18n.catalog[root.dataId && root.dataId === root.availableDataId ? "plan.matching_data" : "plan.needs_matching_data"]
                wrapMode: Text.WrapAnywhere
                color: Theme.PixelTheme.inkMuted
                font.pixelSize: Theme.PixelTheme.fontSm
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 340
                spacing: Theme.PixelTheme.spacingMd
                GridLayout {
                    Layout.preferredWidth: 460
                    Layout.maximumWidth: 460
                    Layout.fillHeight: true
                    columns: 3
                    columnSpacing: 8
                    rowSpacing: 6
                    Components.LabeledTextField { id: features; objectName: "intradayResearchFeatures"; Layout.columnSpan: 3; label: root.i18n.catalog["quant.common_features"] }
                    Components.LabeledTextField { id: trainEnd; objectName: "intradayResearchTrainEnd"; label: root.i18n.catalog["quant.intraday_train_end"] }
                    Components.LabeledTextField { id: valEnd; objectName: "intradayResearchValidationEnd"; label: root.i18n.catalog["quant.intraday_validation_end"] }
                    Components.LabeledTextField { id: testEnd; objectName: "intradayResearchTestEnd"; label: root.i18n.catalog["quant.intraday_test_end"] }
                    Components.LabeledTextField { id: trainDays; objectName: "intradayResearchTrainDays"; label: root.i18n.catalog["quant.intraday_train_days"]; text: "20" }
                    Components.LabeledTextField { id: valDays; objectName: "intradayResearchValidationDays"; label: root.i18n.catalog["quant.intraday_validation_days"]; text: "5" }
                    Components.LabeledTextField { id: stepDays; objectName: "intradayResearchStepDays"; label: root.i18n.catalog["quant.intraday_step_days"]; text: "5" }
                    Components.LabeledTextField { id: commission; objectName: "intradayResearchCommission"; label: root.i18n.catalog["quant.commission_bps"] }
                    Components.LabeledTextField { id: slippage; objectName: "intradayResearchSlippage"; label: root.i18n.catalog["quant.slippage_bps"] }
                    Components.LabeledTextField { id: maxHold; objectName: "intradayResearchMaxHold"; label: root.i18n.catalog["quant.intraday_max_hold"]; text: "12" }
                    Components.LabeledTextField { id: entryDelay; objectName: "intradayResearchEntryDelay"; label: root.i18n.catalog["quant.intraday_entry_delay"]; text: "15" }
                    Components.LabeledTextField { id: stopNew; objectName: "intradayResearchStopNew"; label: root.i18n.catalog["quant.intraday_stop_new"]; text: "30" }
                    Components.LabeledTextField { id: flatten; objectName: "intradayResearchFlatten"; label: root.i18n.catalog["quant.intraday_flatten"]; text: "5" }
                }
                StrategyListEditor {
                    id: editor
                    objectName: "intradayStrategyEditor"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    i18n: root.i18n
                    featureOptions: root.featureOptions
                    defaultFeature: features.text.split(",")[0].trim()
                }
            }
            RowLayout {
                Components.PixelButton {
                    objectName: "intradayComparisonPlanSave"
                    visible: root.savePlan !== null
                    enabled: !operationRuntime.busy
                    text: root.i18n.catalog["plan.save_comparison"]
                    onClicked: root.savePlan(root.values())
                }
                Item { Layout.fillWidth: true }
                Components.PixelButton {
                    objectName: "intradayResearchSettingsDone"
                    text: root.i18n.catalog["quant.intraday_apply_settings"]
                    onClicked: { editor.commit(); root.close() }
                }
            }
            Label {
                Layout.fillWidth: true
                visible: root.errorText.length > 0
                text: root.errorText
                wrapMode: Text.WordWrap
                color: Theme.PixelTheme.ink
                font.pixelSize: Theme.PixelTheme.fontSm
            }
        }
    }
}
