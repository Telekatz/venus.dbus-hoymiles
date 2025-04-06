import QtQuick 1.1
import com.victron.velib 1.0
import "utils.js" as Utils

MbPage {
	id: root
	property string bindPrefix
	property int productId
	property string controlSettings: "com.victronenergy.settings/Settings/Devices/mPlus_0"

	Component {
		id: mbOptionFactory
		MbOption {}
	}

	function getAcLoadList(acLoads)
	{
		var options = [];

		var params = {
			"description": 'Internal',
			"value": 0,
		}
		options.push(mbOptionFactory.createObject(root, params));

		if (!acLoads)
			return options;

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

	VBusItem {
		id: advancedSettings
		bind: Utils.path(controlSettings, "/AdvancedSettings")
	}

	model: VisibleItemModel {

		MbSwitch {
			id: startLimiter
			bind: Utils.path(controlSettings, "/StartLimit")
			name: qsTr("Startup Limit")
		}
		
		MbSpinBox {
			id: startLimiterMin
			description: qsTr("Startup Limit Min")
			show: startLimiter.checked
			item {
				bind: Utils.path(controlSettings, "/StartLimitMin")
				unit: "W"
				decimals: 0
				step: 50
				max: 2000
				min: 50
			}
		}

		MbSpinBox {
			id: startLimiterMax
			description: qsTr("Startup Limit Max")
			show: startLimiter.checked
			item {
				bind: Utils.path(controlSettings, "/StartLimitMax")
				unit: "W"
				decimals: 0
				step: 50
				max: 2000
				min: 50
			}
		}

		MbItemOptions {
			id: limitMode
			description: qsTr("Feed-In Limit Mode")
			bind: Utils.path(controlSettings, "/LimitMode")
			readonly: false
			editable: true
			possibleValues:[
				MbOption{description: qsTr("Maximum Power"); value: 0 },
				MbOption{description: qsTr("Grid Target"); value: 1 },
				MbOption{description: qsTr("Base Load"); value: 2 },
				MbOption{description: qsTr("Venus OS"); value: 3 },
				MbOption{description: qsTr("External"); value: 4 }
			]
		}

		MbSpinBox {	
			id: gridTargetPower
			show: limitMode.value === 1
			description: qsTr("Grid Target Power")
			item {
				bind: "com.victronenergy.settings/Settings/CGwacs/AcPowerSetPoint"
				unit: "W"
				decimals: 0
				step: 10
			}
		}

		MbSpinBox {
			id: gridTargetFastDeviation
			show: limitMode.value === 1
			description: qsTr("Grid Target Fast Deviation")
			item {
				bind: Utils.path(controlSettings, "/GridTargetFastDeviation")
				unit: "W"
				decimals: 0
				step: 5
				max: 100
				min: 10
			}
		}

		MbSpinBox {
			id: gridTargetFastInterval
			show: limitMode.value === 1
			description: qsTr("Grid Target Fast Interval")
			item {
				bind: Utils.path(controlSettings, "/GridTargetFastInterval")
				unit: "s"
				decimals: 1
				step: 0.5
				max: 60
				min: 1
			}
		}

		MbSpinBox {
			id: gridTargetSlowDeviation
			show: limitMode.value === 1
			description: qsTr("Grid Target Slow Deviation")
			item {
				bind: Utils.path(controlSettings, "/GridTargetSlowDeviation")
				unit: "W"
				decimals: 0
				step: 1
				max: 100
				min: 1
			}
		}
		
		MbSpinBox {
			id: gridTargetSlowInterval
			show: limitMode.value === 1
			description: qsTr("Grid Target Slow Interval")
			item {
				bind: Utils.path(controlSettings, "/GridTargetSlowInterval")
				unit: "s"
				decimals: 1
				step: 0.5
				max: 60
				min: 2
			}
		}

		MbSpinBox {
			id: gridTargetForcedInterval
			show: limitMode.value === 1
			description: qsTr("Grid Target Forced Interval")
			item {
				bind: Utils.path(controlSettings, "/GridTargetForcedInterval")
				unit: "s"
				decimals: 0
				step: 1
				max: 60
				min: 5
			}
		}

		MbSpinBox {
			id: baseLoadPeriod
			show: limitMode.value === 2
			description: qsTr("Base Load Period")
			item {
				bind: Utils.path(controlSettings, "/BaseLoadPeriod")
				unit: "min"
				decimals: 1
				step: 0.5
				max: 10
				min: 0.5
			}
		}

		MbSpinBox {
			id: inverterMinimumInterval
			show: (limitMode.value === 2 || limitMode.value === 3)
			description: qsTr("Inverter Minimum Interval")
			item {
				bind: Utils.path(controlSettings, "/InverterMinimumInterval")
				unit: "s"
				decimals: 1
				step: 0.5
				max: 15
				min: 1
			}
		}

		MbItemOptions {
			id: acLoad
			description: qsTr("Power Meter")
			bind: Utils.path(controlSettings, "/PowerMeterInstance")
			readonly: false
			editable: true
		}

		MbSpinBox {
			description: "Inverter DC Shutdown Voltage"
			item {
				bind: Utils.path(controlSettings, "/InverterDcShutdownVoltage")
				unit: "V"
				decimals: 2
				step: 0.05
				max: 60
				min: 16
			}
		}

		MbSpinBox {
			description: "Inverter DC Restart Voltage"
			item {
				bind: Utils.path(controlSettings, "/InverterDcRestartVoltage")
				unit: "V"
				decimals: 2
				step: 0.05
				max: 60
				min: 16
			}
		}

		MbSubMenu {
			description: qsTr("Advanced Settings")
			show: advancedSettings.value === 1
			subpage: Component {
				MbPage {
					title: qsTr("Advanced Settings")
					model: VisibleItemModel {


						MbSpinBox {
							id: gridFilterWidth
							show: limitMode.value === 1
							description: qsTr("Grid Filter Width")
							item {
								bind: Utils.path(controlSettings, "/GridFilterWidth")
								unit: "W"
								decimals: 0
								step: 1
								max: 200
								min: 0
							}
						}

						MbSpinBox {
							id: gridFilterFadeOut
							show: limitMode.value === 1
							description: qsTr("Grid Filter Fade Out")
							item {
								bind: Utils.path(controlSettings, "/GridFilterFadeOut")
								unit: "%"
								decimals: 0
								step: 1
								max: 100
								min: 0
							}
						}

						MbSpinBox {
							id: gridFilterWeight
							show: limitMode.value === 1
							description: qsTr("Grid Filter Minimum Weight")
							item {
								bind: Utils.path(controlSettings, "/GridFilterWeight")
								unit: "%"
								decimals: 0
								step: 1
								max: 100
								min: 1
							}
						}

						MbSpinBox {
							id: gridFilterWeightMax
							show: limitMode.value === 1
							description: qsTr("Grid Filter Maximum Weight")
							item {
								bind: Utils.path(controlSettings, "/GridFilterWeightMax")
								unit: "%"
								decimals: 0
								step: 1
								max: 100
								min: 1
							}
						}

						MbSwitch {
							id: debugOut
							bind: Utils.path(controlSettings, "/DebugOutput")
							name: qsTr("Debug Output")
						}

					}
				}
			}
		}

	}
}
