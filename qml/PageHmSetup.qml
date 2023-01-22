import QtQuick 1.1
import com.victron.velib 1.0
import "utils.js" as Utils

MbPage {
	id: root
	property string bindPrefix
	property int productId
	property string settingsPrefix: Utils.path("com.victronenergy.settings/Settings/DTU/", instance.value)
	
	Component {
		id: mbOptionFactory
		MbOption {}
	}

	function getAcLoadList(acLoads)
	{
		if (!acLoads)
			return [];

		var options = [];

		var params = {
			"description": 'Internal',
			"value": 0,
		}
		options.push(mbOptionFactory.createObject(root, params));

		for (var i = 0; i < acLoads.length; i++) {
			var params = {
				"description": acLoads[i].split(':')[0],
				"value": parseInt(acLoads[i].split(':')[1]),
			}
			options.push(mbOptionFactory.createObject(root, params));
		}

		return options;
	}

	VBusItem {
		id: instance
		bind: service.path("/DeviceInstance")
	}

	VBusItem {
		id: acLoads
		bind: service.path("/AvailableAcLoads")
		onValueChanged: acLoad.possibleValues = getAcLoadList(value)
	}

	model: VisualItemModel {
		
		MbSpinBox {
			id: maxInverterPower
			description: qsTr("Maximum Inverter Power")
			item {
				bind: Utils.path(settingsPrefix, "/MaxPower")
				unit: "W"
				decimals: 0
				step: 50
				max: 2000
				min: 50
			}
		}  
		
		MbItemOptions {
			id: phase
			description: qsTr("Phase")
			bind: Utils.path(settingsPrefix, "/Phase")
			readonly: false
			editable: true
			possibleValues:[
				MbOption{description: qsTr("L1"); value: 1 },
				MbOption{description: qsTr("L2"); value: 2 },
				MbOption{description: qsTr("L3"); value: 3 }
			]
		}
		
		MbItemOptions {
			id: acLoad
			description: qsTr("Power Meter")
			bind: Utils.path(settingsPrefix, "/PowerMeterInstance")
			readonly: false
			editable: true
		}
		
		MbEditBoxIp {
			show: true
			description: qsTr("MQTT URL")
			item: VBusItem {
				id: mqttUrl
				isSetting: true
				bind: Utils.path(settingsPrefix, "/MqttUrl")
			}  
		}

		MbEditBox {
			show: true
			description: qsTr("MQTT Inverter Path")
			maximumLength: 35
			item: VBusItem {
				id: mqttPath
				isSetting: true
				bind: Utils.path(settingsPrefix, "/InverterPath")
			} 
		}
		
		MbItemOptions {
			id: dtu
			description: qsTr("DTU")
			bind: Utils.path(settingsPrefix, "/DTU")
			readonly: false
			editable: true
			possibleValues:[
				MbOption{description: qsTr("Ahoy"); value: 0 },
				MbOption{description: qsTr("OpenDTU"); value: 1 }
			]
		}

		MbSwitch {
			id: startLimiter
			bind: Utils.path(settingsPrefix, "/StartLimit")
			name: qsTr("Startup Limit")
			show: true
		}
		
		MbItemOptions {
			id: limitMode
			description: qsTr("Feed-In Limit Mode")
			bind: Utils.path(settingsPrefix, "/LimitMode")
			readonly: false
			editable: true
			possibleValues:[
				MbOption{description: qsTr("Maximum Power"); value: 0 },
				MbOption{description: qsTr("Grid Target"); value: 1 },
				MbOption{description: qsTr("Base Load"); value: 2 }
			]
		}

		MbSpinBox {
			id: gridTargetInterval
			show: limitMode.value === 1
			description: qsTr("Grid Target Interval")
			item {
				bind: Utils.path(settingsPrefix, "/GridTargetInterval")
				unit: "s"
				decimals: 0
				step: 1
				max: 60
				min: 3
			}
		}

		MbSpinBox {
			id: gridTargetPower
			show: limitMode.value === 1
			description: qsTr("Grid Target Power")
			item {
				bind: Utils.path(settingsPrefix, "/GridTargetPower")
				unit: "W"
				decimals: 0
				step: 5
				max: 200
				min: -100
			}
		}

		MbSpinBox {
			id: gridTargetDevMin
			show: limitMode.value === 1
			description: qsTr("Grid Target Tolerance Minimum")
			item {
				bind: Utils.path(settingsPrefix, "/GridTargetDevMin")
				unit: "W"
				decimals: 0
				step: 5
				max: 100
				min: 5
			}
		}

		MbSpinBox {
			id: gridTargetDevMax
			show: limitMode.value === 1
			description: qsTr("Grid Target Tolerance Maximum")
			item {
				bind: Utils.path(settingsPrefix, "/GridTargetDevMax")
				unit: "W"
				decimals: 0
				step: 5
				max: 100
				min: 5
			}
		}

		MbSpinBox {
			id: baseLoadPeriod
			show: limitMode.value === 2
			description: qsTr("Base Load Period")
			item {
				bind: Utils.path(settingsPrefix, "/BaseLoadPeriod")
				unit: "min"
				decimals: 1
				step: 0.5
				max: 10
				min: 0.5
			}
		}

	}
}
