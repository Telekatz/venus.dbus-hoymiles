/* HM settings */
		MbSwitchForced {
			show: productId == 0xfff1 && item.valid
			name: qsTr("Enabled")
			item.bind: Utils.path(root.bindPrefix, "/Enabled")
		}
		
		MbSpinBox {
			show: productId == 0xfff1
			description: qsTr("Maximum Inverter Power")
			VBusItem {
				id: serialMicroEss
				bind: Utils.path(root.bindPrefix, "/Serial")
			}
			item {
				bind: Utils.path("com.victronenergy.settings/Settings/Devices/mInv_", serialMicroEss.value, "/MaxPower")
				unit: "W"
				decimals: 0
				step: 50
				max: 2000
				min: 50
			}
		}

			MbItemOptions {
			id: microEssPhase
			show: productId == 0xfff1
			description: qsTr("Phase")
			bind: Utils.path("com.victronenergy.settings/Settings/Devices/mInv_", serialMicroEss.value, "/Phase")
			readonly: false
			editable: true
			possibleValues:[
				MbOption{description: qsTr("L1"); value: 1 },
				MbOption{description: qsTr("L2"); value: 2 },
				MbOption{description: qsTr("L3"); value: 3 }
			]
		}
		
		MbEditBoxIp {
			show: productId == 0xfff1
			description: qsTr("MQTT URL")
			item: VBusItem {
				isSetting: true
				bind: Utils.path("com.victronenergy.settings/Settings/Devices/mInv_", serialMicroEss.value, "/MqttUrl")
			}  
		}
		
		MbEditBox {
			description: qsTr("MQTT Port")
			show: productId == 0xfff1
			item: VBusItem {
				isSetting: true
				bind: Utils.path("com.victronenergy.settings/Settings/Devices/mInv_", serialMicroEss.value, "/MqttPort")
			}
			matchString: "0123456789"
			maximumLength: 5
			numericOnlyLayout: true
		}

		MbEditBox {
			show: productId == 0xfff1
			description: qsTr("MQTT User")
			item: VBusItem {
				isSetting: true
				bind: Utils.path("com.victronenergy.settings/Settings/Devices/mInv_", serialMicroEss.value, "/MqttUser")
			}  
		}
		
		MbEditBox {
			show: productId == 0xfff1
			description: qsTr("MQTT Password")
			item: VBusItem {
				isSetting: true
				bind: Utils.path("com.victronenergy.settings/Settings/Devices/mInv_", serialMicroEss.value, "/MqttPwd")
			}  
		}

		MbEditBox {
			show: productId == 0xfff1
			description: qsTr("MQTT Inverter Path")
			maximumLength: 35
			item: VBusItem {
				isSetting: true
				bind: Utils.path("com.victronenergy.settings/Settings/Devices/mInv_", serialMicroEss.value, "/InverterPath")
			} 
		}
		
		MbItemOptions {
			id: microEssDtu
			show: productId == 0xfff1
			description: qsTr("DTU")
			bind: Utils.path("com.victronenergy.settings/Settings/Devices/mInv_", serialMicroEss.value, "/DTU")
			readonly: false
			editable: true
			possibleValues:[
				MbOption{description: qsTr("Ahoy"); value: 0 },
				MbOption{description: qsTr("OpenDTU"); value: 1 }
			]
		}

		MbSpinBox {
			show: productId == 0xfff1 && microEssDtu.value === 0
			description: qsTr("Inverter ID")
			item {
				bind: Utils.path("com.victronenergy.settings/Settings/Devices/mInv_", serialMicroEss.value, "/InverterID")
				decimals: 0
				step: 1
				max: 9
				min: 0
			}
		}

		MbSwitch {
			id: autoRestart
			VBusItem {
				id: restart
				bind:  Utils.path(root.bindPrefix, "/Restart")
			}
			show: restart.valid
			bind: Utils.path("com.victronenergy.settings/Settings/Devices/mInv_", serialMicroEss.value, "/AutoRestart")
			name: qsTr("Restart inverter at midnight")
		}
/* HM settings end */
