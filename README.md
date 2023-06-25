# dbus-hoymiles
Integrate Hoymiles microinverters into Victron Energies Venus OS

## Purpose
With the scripts in this repo it should be easy possible to install, uninstall, restart a service that connects Hoymiles microinverters to the VenusOS and GX devices from Victron. 

The script is intended to be used with battery powered Hoymiles inverters. It provides functions to regulate the output power of the inverters to realize a zero export system.
This script cannot be used in a system that already has a Multiplus/Quattro installed.

As interface between the GX device and the Hoymiles microinverter OpenDTU or Ahoy is used:
- https://github.com/tbnobody/OpenDTU
- https://github.com/lumapu/ahoy

## Inspiration
This project is my first on GitHub and with the Victron Venus OS, so I took some ideas and approaches from the following projects - many thanks for sharing the knowledge:
- https://github.com/vikt0rm/dbus-shelly-1pm-pvinverter
- https://github.com/Marv2190/venus.dbus-MqttToGridMeter

## How it works
### System diagram
<img src="img/system_diagram.png" width=800/>

### My setup
- 3-Phase installation
- Venus OS on Raspberry PI (Minimum version V2.92)
- PYLONTECH LiFePO4 Battery
  - Connected over CAN with Waveshare RS485 CAN HAT for Raspberry Pi
- Victron SmartSolar MPPT charge controller
  - Connected over VE.Direct to USB interface  
- Hoymiles HM-600 
  - Connected over https://github.com/tbnobody/OpenDTU
  - Shelly1pm as additional power meter connected over https://github.com/Telekatz/venus.dbus-shellyPlug
- SDM630 used as a grid meter
  - Connected over https://community.victronenergy.com/idea/114716/power-meter-lib-for-modbus-rtu-based-meters-from-a.html

### Pictures
<img src="img/main.png" width=600/>
<img src="img/inverter.png" width=600/>
<img src="img/settings.png" width=600/>

## Install & Configuration
### Get the code
Just grab a copy of the main branch and copy them to a folder under `/data/` e.g. `/dbus-hoymiles`.
After that call the install.sh script.

The following script should do everything for you:
```
wget https://github.com/telekatz/venus.dbus-hoymiles/archive/refs/heads/main.zip
unzip main.zip "venus.dbus-hoymiles-main/*" -d /data
mv /data/venus.dbus-hoymiles-main /data/dbus-hoymiles
chmod a+x /data/dbus-hoymiles/install.sh
/data/dbus-hoymiles/install.sh
rm main.zip
```

Before installing a new version, uninstall the installed version:
```
/data/dbus-hoymiles/uninstall.sh
```

### Change config.ini
Within the project there is a file `/data/dbus-hoymiles/config.ini`. Create a new section for each inverter to be created.

| Section  | Config value | Explanation |
| ------------- | ------------- | ------------- |
| Inverter[n] | Deviceinstance | Unique ID identifying the inverter in Venus OS. |

### Inverter settings
The following settings are available in the device settings menu inside Venus OS:

| Config value | Explanation |
| ------------- | ------------- |
| Enabled | Enables the use of the inverter. |
| Maximum Inverter Power | Maximum power of the inverter. |
| Phase | Valid values L1, L2 or L3: represents the phase where inverter is feeding in. |
| MQTT URL | IP address of the MQTT server. |
| MQTT Port | Port of the MQTT server. |
| MQTT User | Username for the MQTT server. Leave blank if no username/password required. |
| MQTT Password | Password for the MQTT server. Leave blank if no username/password required. |
| MQTT Inverter Path | Path on which the DTU publishes the inverter data. |
| DTU | Type of the DTU. |
| Inverter ID | Number of the inverter in Ahoy. |

The following settings are available only in the settings menu of the first inverter and apply for all created inverters:

| Config value | Explanation |
| ------------- | ------------- |
| Startup Limit | Limits the AC power of the inverter to the generated PV power. |
| Startup Limit Min | Initial limit. |
| Startup Limit Max | Ends the limitation as soon as the generated PV power reaches this value. |
| Feed-In Limit Mode | Selection of the feed in limit mode (Maximum Power, Grid Target Power or Base Load). |
| Grid Target Interval | Minimum power change interval for grid target mode. |
| Grid Target Power | Target power for grid import. |
| Grid Target Tolerance Minimum | Maximal allowed lower deviation from the target grid power. |
| Grid Target Tolerance Maximum | Maximal allowed upper deviation from the target grid power. |
| Base Load Period | Observation period for base load mode. |
| Inverter Minimum Interval | Minimum interval between limit changes. |
| Power Meter | Use of an external power meter instead of internal inverter power meters for the total power. The role of the external power meter must be AC load. |
| Restart inverter at midnight | Restarts the inverter at midnight to reset the yield day counter. |

### Feed-In limit modes

| Mode | Explanation |
| ------------- | ------------- |
| Maximum Power | Inverter power is set to `Maximum Inverter Power`. |
| Grid Target | Imported power from the grid will be regulated to the `Grid Target Power`. New limit will be set, if the grid power exceeds the limits specified by `Grid Target Tolerance Minimum` and `Grid Target Tolerance Maximum`. `Grid Target Interval` specifies the minimum time interval between two limit changes. |
| Base Load | Inverter Power will be regulated to the lowest load power during the past `Base Load Period`. |
| Venus OS | Inverter Power will be regulated by Venus OS. |

## Used documentation
- https://github.com/victronenergy/venus/wiki Victron Energies Venus OS
- https://github.com/victronenergy/venus/wiki/dbus DBus paths for Victron namespace
- https://github.com/victronenergy/venus/wiki/dbus-api DBus API from Victron
- https://github.com/tbnobody/OpenDTU/blob/master/README.md OpenDTU user manual
- https://github.com/lumapu/ahoy/blob/main/Getting_Started.md Ahoy DTU user manual



