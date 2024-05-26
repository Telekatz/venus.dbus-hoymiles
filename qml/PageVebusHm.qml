import QtQuick 1.1
import com.victron.velib 1.0
import "utils.js" as Utils

MbPage {
	id: root

	property variant service
	property string bindPrefix
	property VBusItem instance: VBusItem { bind: service.path("/DeviceInstance") }
	property string settingsPrefix: Utils.path("com.victronenergy.settings/Settings/DTU/", instance.value)

	property VBusItem phase: VBusItem {bind: Utils.path(settingsPrefix, "/Phase") }
	property VBusItem acPower: VBusItem {bind: service.path("/Ac/Power"); unit: "W" }

	title: service.description
	summary: acPower.valid ? acPower.format(0) : qsTr("Not connected")

	SystemState {
		id: state
		bind: service.path("/State")
	}

	model: VisibleItemModel {

		MbItemOptions {
			description: qsTr("Switch")
			bind: service.path("/Mode")

			possibleValues: [
				MbOption { description: qsTr("Off"); value: 4 },
				MbOption { description: qsTr("Charger Only"); value: 1; readonly: true },
				MbOption { description: qsTr("Inverter Only"); value: 2 },
				MbOption { description: qsTr("On"); value: 3 }
			]

			VBusItem {
				id: modeIsAdjustable
				bind: service.path("/ModeIsAdjustable")
			}
			readonly: !modeIsAdjustable.valid || !modeIsAdjustable.value
		}

		MbItemRow {
			description: "DC"
			VBusItem {
				id: dcCurrent
				bind: service.path("/Dc/0/Current")
				unit: "A"
			}

			values: [
				MbTextBlock { item.bind: service.path("/Dc/0/Voltage"); width: 80; height: 25 },
				MbTextBlock { item.value: dcCurrent.absFormat(1); width: 100; height: 25 },
				MbTextBlock { item.bind: service.path("/Dc/0/Power"); width: 120; height: 25 }
			]
		}

		MbItemRow {
			description: qsTr("AC Phase L1")
			VBusItem {
				id: acPowerL1
				bind: service.path("/Ac/ActiveIn/L1/P")
				unit: "W"
			}

			values: [
				MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L1/V"); width: 80; height: 25 },
				MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L1/I"); width: 100; height: 25 },
				MbTextBlock { item.value: acPowerL1.absFormat(1); width: 120; height: 25 }
			]
		}

		MbItemRow {
			description: qsTr("AC Phase L2")
			VBusItem {
				id: acPowerL2
				bind: service.path("/Ac/ActiveIn/L2/P")
				unit: "W"
			}

			values: [
				MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L2/V"); width: 80; height: 25 },
				MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L2/I"); width: 100; height: 25 },
				MbTextBlock { item.value: acPowerL2.absFormat(1); width: 120; height: 25 }
			]
		}

		MbItemRow {
			description: qsTr("AC Phase L3")
			VBusItem {
				id: acPowerL3
				bind: service.path("/Ac/ActiveIn/L3/P")
				unit: "W"
			}

			values: [
				MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L3/V"); width: 80; height: 25 },
				MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L3/I"); width: 100; height: 25 },
				MbTextBlock { item.value: acPowerL3.absFormat(1); width: 120; height: 25 }
			]
		}

		MbItemValue {
		description: qsTr("Energy")
		item.bind: service.path("/Energy/InverterToAcIn1")
		}

		MbItemValue {
			description: qsTr("Efficiency")
			show: item.valid
			item.bind: service.path("/Ac/Efficiency")
		}
		
		MbItemValue {
			description: qsTr("Feed-in Power Limit")
			show: item.valid
			item.bind: service.path("/Ac/PowerLimit")
		}

		MbItemValue {
			description: qsTr("Temperature")
			show: item.valid
			item.bind: service.path("/Temperature")
		}

		MbSubMenu {
			description: qsTr("Setup")
			subpage: PageHmSetup {
				title: qsTr("Setup")
				bindPrefix: root.bindPrefix
				productId: productIdItem.valid ? productIdItem.value : 0
			}
		}

		MbSubMenu {
			id: deviceItem
			description: qsTr("Device")
			subpage: Component {
				PageDeviceInfo {
					title: deviceItem.description
					bindPrefix: root.bindPrefix

				}
			}
		}
	}
}
