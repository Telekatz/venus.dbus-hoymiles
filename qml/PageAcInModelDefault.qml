import QtQuick 1.1

VisualItemModel {
	id: meterModel

	property string acTotalPower: _acTotalPower.item.text
	property variant summary: connected.value === 1 ? acTotalPower : qsTr("Not connected")
	property VBusItem connected: VBusItem { id: connected; bind: service.path("/Connected") }

	function formatCgErrorCode(value)
	{
		if (value === undefined)
			return "";
		var text = qsTr("No error");
		switch (value) {
		case 1:
			text = qsTr("Front selector locked");
			break;
		}
		return text + " (" + value.toString() + ")";
	}

	function formatStatus(text, value)
	{
		return text + " (" + value.toString() + ")";
	}

	MbItemOptions {
		description: qsTr("Status")
		bind: productIdItem.value === froniusInverterProductId ? service.path("/StatusCode") : ""
		readonly: true
		show: productIdItem.value === froniusInverterProductId
		possibleValues: [
			MbOption { description: formatStatus(qsTr("Startup"), 0); value: 0 },
			MbOption { description: formatStatus(qsTr("Startup"), 1); value: 1 },
			MbOption { description: formatStatus(qsTr("Startup"), 2); value: 2 },
			MbOption { description: formatStatus(qsTr("Startup"), 3); value: 3 },
			MbOption { description: formatStatus(qsTr("Startup"), 4); value: 4 },
			MbOption { description: formatStatus(qsTr("Startup"), 5); value: 5 },
			MbOption { description: formatStatus(qsTr("Startup"), 6); value: 6 },
			MbOption { description: qsTr("Running"); value: 7 },
			MbOption { description: qsTr("Standby"); value: 8 },
			MbOption { description: qsTr("Boot loading"); value: 9 },
			MbOption { description: qsTr("Error"); value: 10 },
			MbOption { description: qsTr("Running (MPPT)"); value: 11 },
			MbOption { description: qsTr("Running (Throttled)"); value: 12 }
		]
	}

	MbItemValue {
		description: qsTr("Error Code")
		item.bind: show ? service.path("/ErrorCode") : ""
		show: productIdItem.value === froniusInverterProductId
	}

	MbItemValue {
		description: qsTr("Error Code")
		item.text: formatCgErrorCode(cgErrorCode.value)
		show: productIdItem.value === carloGavazziEmProductId

		VBusItem {
			id: cgErrorCode
			bind: productIdItem.value === carloGavazziEmProductId ? service.path("/ErrorCode") : ""
		}
	}
  
  MbItemRow {
		description: "DC"
    show: productIdItem.value === 0xFFF1
		values: [
			MbTextBlock { item.bind: service.path("/Dc/Voltage"); width: 80; height: 25 },
			MbTextBlock { item.bind: service.path("/Dc/Current"); width: 100; height: 25 },
			MbTextBlock { item.bind: service.path("/Dc/Power"); width: 120; height: 25 }
		]
	}

	MbItemRow {
		description: qsTr("AC Phase L1")
		values: [
			MbTextBlock { item.bind: service.path("/Ac/L1/Voltage"); width: 80; height: 25 },
			MbTextBlock { item.bind: service.path("/Ac/L1/Current"); width: 100; height: 25 },
			MbTextBlock { item.bind: service.path("/Ac/L1/Power"); width: 120; height: 25 }
		]
	}

	MbItemRow {
		description: qsTr("AC Phase L2")
		values: [
			MbTextBlock { item.bind: service.path("/Ac/L2/Voltage"); width: 80; height: 25 },
			MbTextBlock { item.bind: service.path("/Ac/L2/Current"); width: 100; height: 25 },
			MbTextBlock { item.bind: service.path("/Ac/L2/Power"); width: 120; height: 25 }
		]
	}

	MbItemRow {
		description: qsTr("AC Phase L3")
		values: [
			MbTextBlock { item.bind: service.path("/Ac/L3/Voltage"); width: 80; height: 25 },
			MbTextBlock { item.bind: service.path("/Ac/L3/Current"); width: 100; height: 25 },
			MbTextBlock { item.bind: service.path("/Ac/L3/Power"); width: 120; height: 25 }
		]
	}

	MbItemRow {
		height: 70
		description: qsTr("AC Totals")
		values: MbColumn {
			MbRow {
				MbTextBlock { item.bind: service.path("/Ac/Current"); width: 100; height: 25 }
				MbTextBlock { id: _acTotalPower; item.bind: service.path("/Ac/Power"); width: 120; height: 25 }
			}
			MbTextBlock { anchors.right: parent.right; item.bind: service.path("/Ac/Energy/Forward"); width: 120; height: 25 }
		}
	}

	MbItemValue {
		description: qsTr("Energy L1")
		item.bind: service.path("/Ac/L1/Energy/Forward")
	}

	MbItemValue {
		description: qsTr("Energy L2")
		item.bind: service.path("/Ac/L2/Energy/Forward")
	}

	MbItemValue {
		description: qsTr("Energy L3")
		item.bind: service.path("/Ac/L3/Energy/Forward")
	}

	MbItemValue {
		description: qsTr("Zero feed-in power limit")
		show: item.valid
		item.bind: service.path("/Ac/PowerLimit")
	}

	MbItemOptions {
		description: qsTr("Phase Sequence")
		bind: service.path("/PhaseSequence")
		readonly: true
		show: valid
		possibleValues: [
			MbOption { description: qsTr("L1-L2-L3"); value: 0 },
			MbOption { description: qsTr("L1-L3-L2"); value: 1 }
		]
	}

	MbSubMenu {
		description: qsTr("Setup")
		show: subpage.show
		subpage: PageAcInSetup {
			title: qsTr("Setup")
			bindPrefix: root.bindPrefix
			productId: productIdItem.valid ? productIdItem.value : 0
		}
	}
  
  MbSubMenu {
		description: qsTr("Setup")
		show: productIdItem.value === 0xFFF1
		subpage: PageHmSetup {
			title: qsTr("Setup")
			bindPrefix: root.bindPrefix
			productId: productIdItem.valid ? productIdItem.value : 0
		}
	}
  
	MbSubMenu {
		description: qsTr("Device")
		subpage: Component {
			PageDeviceInfo {
				title: qsTr("Device")
				bindPrefix: root.bindPrefix

				MbItemValue {
					description: qsTr("Data manager version")
					item.bind: service.path("/DataManagerVersion")
					show: item.valid
				}
			}
		}
	}
}

