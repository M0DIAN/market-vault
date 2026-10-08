import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components" as Components
import "../theme" as Theme

ColumnLayout {
    id: root
    objectName: "quantStrategyListEditor"
    required property var i18n
    property var featureOptions: []
    property string defaultFeature: featureOptions[0] || ""
    property var strategies: []
    property var conditionDraft: []
    property int selectedIndex: 0
    property string selectedKind: "FEATURE_RULE"
    property string matchChoice: "ALL"
    readonly property var kinds: ["FEATURE_RULE", "RIDGE", "COMPOSITE_RULE"]
    readonly property var comparators: ["GT", "GE", "LT", "LE"]
    spacing: 6

    function clone(value) { return JSON.parse(JSON.stringify(value)) }
    function condition(feature) { return {"signal_field": feature, "comparator": "GT", "threshold": "0"} }
    function reset(feature) {
        root.strategies = [
            {"kind": "FEATURE_RULE", "name": "Trend", "signal_field": feature, "comparator": "GT", "threshold": "0"},
            {"kind": "FEATURE_RULE", "name": "MeanReversion", "signal_field": feature, "comparator": "LT", "threshold": "0"},
            {"kind": "RIDGE", "name": "Ridge", "alpha": "1", "threshold": "0"}
        ]
        load(0)
    }
    function load(index) {
        if (index < 0 || index >= root.strategies.length) return
        root.selectedIndex = index
        const item = root.strategies[index]
        root.selectedKind = item.kind
        selector.currentIndex = index
        nameField.text = item.name
        kindField.currentIndex = root.kinds.indexOf(item.kind)
        alphaField.text = String(item.alpha === undefined ? 1 : item.alpha)
        ridgeThreshold.text = String(item.threshold === undefined ? 0 : item.threshold)
        root.matchChoice = item.match === "ANY" ? "ANY" : "ALL"
        matchField.currentIndex = root.matchChoice === "ANY" ? 1 : 0
        root.conditionDraft = item.kind === "COMPOSITE_RULE" ? clone(item.conditions)
            : item.kind === "FEATURE_RULE" ? [{"signal_field": item.signal_field,
                "comparator": item.comparator, "threshold": item.threshold}] : []
    }
    function commit() {
        if (!root.strategies.length) return
        const items = clone(root.strategies)
        const item = {"kind": root.selectedKind, "name": nameField.text}
        if (root.selectedKind === "RIDGE") {
            item.alpha = alphaField.text
            item.threshold = ridgeThreshold.text
        } else if (root.selectedKind === "COMPOSITE_RULE") {
            item.match = matchField.currentIndex === 1 ? "ANY" : "ALL"
            item.conditions = clone(root.conditionDraft)
        } else {
            const rule = root.conditionDraft[0]
            item.signal_field = rule.signal_field
            item.comparator = rule.comparator
            item.threshold = rule.threshold
        }
        items[root.selectedIndex] = item
        root.strategies = items
        selector.currentIndex = root.selectedIndex
    }
    function snapshot() { commit(); return clone(root.strategies) }
    function select(index) { commit(); load(index) }
    function addStrategy() {
        commit()
        const items = clone(root.strategies)
        let number = items.length + 1
        while (items.some(item => item.name === "Strategy " + number)) ++number
        items.push({"kind": "FEATURE_RULE", "name": "Strategy " + number,
                    "signal_field": root.defaultFeature, "comparator": "GT", "threshold": "0"})
        root.strategies = items
        load(items.length - 1)
    }
    function removeStrategy() {
        if (root.strategies.length <= 1) return
        const items = clone(root.strategies)
        items.splice(root.selectedIndex, 1)
        root.strategies = items
        load(Math.min(root.selectedIndex, items.length - 1))
    }
    function changeKind(index) {
        commit()
        const items = clone(root.strategies)
        const feature = root.conditionDraft.length ? root.conditionDraft[0].signal_field : root.defaultFeature
        const item = {"kind": root.kinds[index], "name": nameField.text}
        if (item.kind === "RIDGE") { item.alpha = "1"; item.threshold = "0" }
        else if (item.kind === "COMPOSITE_RULE") {
            item.match = "ALL"; item.conditions = [condition(feature), condition(feature)]
        } else {
            item.signal_field = feature; item.comparator = "GT"; item.threshold = "0"
        }
        items[root.selectedIndex] = item
        root.strategies = items
        load(root.selectedIndex)
    }
    function setCondition(index, field, value) {
        // Keep draft delegates alive while typing; commit publishes the list.
        root.conditionDraft[index][field] = value
    }
    function addCondition() {
        const items = clone(root.conditionDraft)
        items.push(condition(root.defaultFeature))
        root.conditionDraft = items
    }
    function removeCondition(index) {
        if (root.conditionDraft.length <= 2) return
        const items = clone(root.conditionDraft)
        items.splice(index, 1)
        root.conditionDraft = items
    }

    RowLayout {
        Layout.fillWidth: true
        Components.PixelComboBox {
            id: selector
            objectName: "quantStrategySelector"
            Layout.fillWidth: true
            model: root.strategies.map(item => item.name)
            onActivated: index => root.select(index)
        }
        Components.PixelButton {
            objectName: "quantStrategyAddButton"
            text: root.i18n.catalog["quant.add_strategy"]
            enabled: root.featureOptions.length > 0
            onClicked: root.addStrategy()
        }
        Components.PixelButton {
            objectName: "quantStrategyRemoveButton"
            text: root.i18n.catalog["quant.remove_strategy"]
            enabled: root.strategies.length > 1
            onClicked: root.removeStrategy()
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Components.LabeledTextField {
            id: nameField
            objectName: "quantStrategyName"
            Layout.maximumWidth: 10000
            label: root.i18n.catalog["quant.strategy_name"]
        }
        Components.LabeledComboBox {
            id: kindField
            objectName: "quantStrategyKind"
            Layout.maximumWidth: 10000
            label: root.i18n.catalog["quant.strategy_kind"]
            model: [root.i18n.catalog["quant.feature_rule"], "Ridge", root.i18n.catalog["quant.composite_rule"]]
            onSelected: root.changeKind(currentIndex)
            onModelChanged: currentIndex = root.kinds.indexOf(root.selectedKind)
        }
    }
    RowLayout {
        visible: root.selectedKind === "RIDGE"
        Layout.fillWidth: true
        Components.LabeledTextField {
            id: alphaField
            objectName: "quantStrategyAlpha"
            label: root.i18n.catalog["quant.ridge_alpha"]
        }
        Components.LabeledTextField {
            id: ridgeThreshold
            objectName: "quantStrategyRidgeThreshold"
            label: root.i18n.catalog["quant.ridge_threshold"]
        }
    }
    RowLayout {
        visible: root.selectedKind === "COMPOSITE_RULE"
        Layout.fillWidth: true
        Label {
            text: root.i18n.catalog["quant.condition_match"]
            color: Theme.PixelTheme.inkMuted
        }
        Components.PixelComboBox {
            id: matchField
            objectName: "quantStrategyMatch"
            Layout.fillWidth: true
            model: [root.i18n.catalog["quant.match_all"], root.i18n.catalog["quant.match_any"]]
            onActivated: root.matchChoice = currentIndex === 1 ? "ANY" : "ALL"
            onModelChanged: currentIndex = root.matchChoice === "ANY" ? 1 : 0
        }
        Components.PixelButton {
            objectName: "quantConditionAddButton"
            text: root.i18n.catalog["quant.add_condition"]
            onClicked: root.addCondition()
        }
    }
    Label {
        visible: root.selectedKind !== "RIDGE"
        text: root.i18n.catalog["quant.condition_columns"]
        color: Theme.PixelTheme.inkMuted
        font.pixelSize: Theme.PixelTheme.fontSm
    }
    ListView {
        objectName: "quantStrategyConditions"
        visible: root.selectedKind !== "RIDGE"
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 36
        clip: true
        spacing: 4
        model: root.conditionDraft
        ScrollBar.vertical: ScrollBar {}
        delegate: RowLayout {
            id: conditionRow
            required property int index
            required property var modelData
            width: ListView.view.width - 12
            height: 32
            Components.PixelComboBox {
                objectName: "quantConditionFeature" + index
                Layout.fillWidth: true
                Layout.minimumWidth: 90
                model: root.featureOptions
                currentIndex: Math.max(0, root.featureOptions.indexOf(modelData.signal_field))
                onActivated: chosen => root.setCondition(conditionRow.index, "signal_field", currentText)
            }
            Components.PixelComboBox {
                objectName: "quantConditionComparator" + index
                Layout.preferredWidth: 68
                model: [">", ">=", "<", "<="]
                currentIndex: root.comparators.indexOf(modelData.comparator)
                onActivated: chosen => root.setCondition(conditionRow.index, "comparator", root.comparators[chosen])
            }
            Components.PixelTextField {
                objectName: "quantConditionThreshold" + index
                Layout.preferredWidth: 80
                text: String(modelData.threshold)
                onTextEdited: root.setCondition(conditionRow.index, "threshold", text)
            }
            Components.PixelButton {
                objectName: "quantConditionRemove" + index
                visible: root.selectedKind === "COMPOSITE_RULE"
                Layout.preferredWidth: 30
                Layout.minimumWidth: 30
                Layout.maximumWidth: 30
                text: "−"
                enabled: root.conditionDraft.length > 2
                onClicked: root.removeCondition(conditionRow.index)
            }
        }
    }
    Item { visible: root.selectedKind === "RIDGE"; Layout.fillHeight: true }
}
