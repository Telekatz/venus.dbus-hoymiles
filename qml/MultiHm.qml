import QtQuick 1.1
import com.victron.velib 1.0
import "utils.js" as Utils

MbIcon {
	id: multi
	iconId: "overview-inverter-Hm"

	property string vebusPrefix: ""
	property string systemPrefix: "com.victronenergy.system"
	property VBusItem systemState: VBusItem { bind: Utils.path(systemPrefix, "/SystemState/State") }

	property VBusItem vebusPath: VBusItem { bind: "com.victronenergy.system/VebusService" }
	property VBusItem multiPower: VBusItem { bind: Utils.path(vebusPath.value, "/Ac/ActiveIn/P"); unit: "W" }

	Component.onCompleted: discoverMultis()

	Text {
		anchors {
			horizontalCenter: multi.horizontalCenter
			top: multi.top; topMargin: 8
		}
		horizontalAlignment: Text.AlignHCenter
		color: "white"
		font {pixelSize: 16; bold: true}
		text: vebusState.text

		SystemState {
			id: vebusState
			bind: systemState.valid?Utils.path(systemPrefix, "/SystemState/State"):Utils.path(sys.vebusPrefix, "/State")
		}
	}

	Text {
		anchors {
			horizontalCenter: multi.horizontalCenter
			top: multi.top; topMargin: 40
		}
		horizontalAlignment: Text.AlignHCenter
		color: "white"
		show: multiPower.valid
		font {pixelSize: 25}
		text: multiPower.absFormat(0)

	}

	// When a new service is found check if is a multi
	Connections {
		target: DBusServices
		onDbusServiceFound: addService(service)
	}

	function addService(service)
	{
		if (service.type === DBusService.DBUS_SERVICE_MULTI) {
			if (vebusPrefix === "")
				vebusPrefix = service.name;
		}
	}

	// Check available services to find multis
	function discoverMultis()
	{
		for (var i = 0; i < DBusServices.count; i++) {
			if (DBusServices.at(i).type === DBusService.DBUS_SERVICE_MULTI) {
				addService(DBusServices.at(i))
			}
		}
	}
}

