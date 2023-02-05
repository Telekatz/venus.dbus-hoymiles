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

	model: VisualItemModel {

		MbItemRow {
			description: "DC"
			VBusItem {
				id: dcCurrent
				bind: service.path("/Dc/1/Current")
				unit: "A"
			}

			values: [
				MbTextBlock { item.bind: service.path("/Dc/0/Voltage"); width: 80; height: 25 },
				MbTextBlock { item.value: dcCurrent.absFormat(1); width: 100; height: 25 },
				MbTextBlock { item.bind: service.path("/Dc/1/Power"); width: 120; height: 25 }
			]
		}

		MbItemRow {
			height: 70
			description: qsTr("AC Phase L1")
			show: phase.value === 1
			values: MbColumn {
				spacing: 2
				VBusItem {
					id: acPowerL1
					bind: service.path("/Ac/Inverter/L1/P")
					unit: "W"
				}
				MbRow {
					MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L1/V"); width: 100; height: 30 }
					MbTextBlock { item.bind: service.path("/Ac/Inverter/L1/I"); width: 100; height: 30 }
				}
				MbRow {
					MbTextBlock { item.value: acPowerL1.absFormat(1); width: 100; height: 30 }
					MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L1/F"); width: 100; height: 30 }
				}
			}
		}

		MbItemRow {
			height: 70
			description: qsTr("AC Phase L2")
			show: phase.value === 2
			values: MbColumn {
				spacing: 2
				VBusItem {
					id: acPowerL2
					bind: service.path("/Ac/Inverter/L2/P")
					unit: "W"
				}
				MbRow {
					MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L2/V"); width: 100; height: 30 }
					MbTextBlock { item.bind: service.path("/Ac/Inverter/L2/I"); width: 100; height: 30 }
				}

				MbRow {
					MbTextBlock { item.value: acPowerL2.absFormat(1); width: 100; height: 30 }
					MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L2/F"); width: 100; height: 30 }
				}
			}
		}

		MbItemRow {
			height: 70
			description: qsTr("AC Phase L3")
			show: phase.value === 3
			values: MbColumn {
				spacing: 2
				VBusItem {
					id: acPowerL3
					bind: service.path("/Ac/Inverter/L3/P")
					unit: "W"
				}
				MbRow {
					MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L3/V"); width: 100; height: 30}
					MbTextBlock { item.bind: service.path("/Ac/Inverter/L3/I"); width: 100; height: 30}
				}

				MbRow {
					MbTextBlock { item.value: acPowerL3.absFormat(1); width: 100; height: 30}
					MbTextBlock { item.bind: service.path("/Ac/ActiveIn/L3/F"); width: 100; height: 30}
				}
			}
		}

		MbItemValue {
		description: qsTr("Energy")
		item.bind: service.path("/Ac/Energy/Forward")
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
