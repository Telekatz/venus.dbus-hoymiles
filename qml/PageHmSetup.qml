import QtQuick 1.1
import com.victron.velib 1.0
import "utils.js" as Utils

MbPage {
	id: root
	property string bindPrefix
	property int productId
	property string settingsPrefix: Utils.path("com.victronenergy.settings/Settings/Ahoy/", instance.value)
  
	VBusItem {
		id: instance
		bind: service.path("/DeviceInstance")
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
    
	MbEditBox {
		show: true
		description: qsTr("MQTT Inverter Path")
		maximumLength: 35
		item: VBusItem {
			id: mqttPath
			isSetting: true
			bind: Utils.path(settingsPrefix, "/InverterPath")
			text:  value
		} 
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

	MbSwitch {
		id: shelly
			bind: Utils.path(settingsPrefix, "/Shelly/Enable")
			name: qsTr("Activate Shelly")
			show: true
		}
    
	MbSwitch {
		id: shellyPowerMeter
			bind: Utils.path(settingsPrefix, "/Shelly/PowerMeter")
			name: qsTr("Shelly Power Meter")
			show: shelly.checked
		}
    
	MbEditBoxIp {
		show: shelly.checked
		description: qsTr("Shelly IP Address")
		item: VBusItem {
			id: shellyIpaddress
			isSetting: true
			bind: Utils.path(settingsPrefix, "/Shelly/Url")
			text:  value
		}  
		}
    
	MbEditBox {
		show: shelly.checked
		description: qsTr("Shelly User Name")
		maximumLength: 35
		item: VBusItem {
			id: shellyUserName
			isSetting: true
			bind: Utils.path(settingsPrefix, "/Shelly/Username")
			text:  value
		} 
	}
    
	MbEditBox {
		show: shelly.checked
		description: qsTr("Shelly Password")
		maximumLength: 35
		item: VBusItem {
			id: shellyPassword
			isSetting: true
			bind: Utils.path(settingsPrefix, "/Shelly/Password")
			text:  value
		} 
	}
    
    
    
	}
}
