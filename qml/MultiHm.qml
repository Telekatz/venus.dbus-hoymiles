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
	property VBusItem debug0: VBusItem { bind: Utils.path(vebusPath.value, "/Debug/Debug0") }
	property VBusItem debug1: VBusItem { bind: Utils.path(vebusPath.value, "/Debug/Debug1") }
	property VBusItem debug2: VBusItem { bind: Utils.path(vebusPath.value, "/Debug/Debug2") }
	property VBusItem debug3: VBusItem { bind: Utils.path(vebusPath.value, "/Debug/Debug3") }

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
		visible: multiPower.valid
		font {pixelSize: 25}
		text: multiPower.absFormat(0)

	}

	Text {
		anchors {
			left: multi.left; leftMargin: 10
			top: multi.top; topMargin: 70
		}
		horizontalAlignment: Text.AlignHCenter
		color: "white"
		visible: debug0.valid
		font {pixelSize: 16}
		text: debug0.value

	}

	Text {
		anchors {
			left: multi.left; leftMargin: 10
			top: multi.top; topMargin: 90
		}
		horizontalAlignment: Text.AlignHCenter
		color: "white"
		visible: debug1.valid
		font {pixelSize: 16}
		text: debug1.value

	}

	Text {
		anchors {
			right: multi.right; rightMargin: 10
			top: multi.top; topMargin: 70
		}
		horizontalAlignment: Text.AlignHCenter
		color: "white"
		visible: debug2.valid
		font {pixelSize: 16}
		text: debug2.value

	}

	Text {
		anchors {
			right: multi.right; rightMargin: 10
			top: multi.top; topMargin: 90
		}
		horizontalAlignment: Text.AlignHCenter
		color: "white"
		visible: debug3.valid
		font {pixelSize: 16}
		text: debug3.value

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

