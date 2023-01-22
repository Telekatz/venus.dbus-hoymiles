#!/usr/bin/env python

# import normal packages
import platform
import logging
import sys
import os
import sys
if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject
import sys
import json
import time
import configparser # for config/ini file
import paho.mqtt.client as mqtt
import requests # for http GET

try:
  import thread   # for daemon = True  / Python 2.x
except:
  import _thread as thread   # for daemon = True  / Python 3.x
import dbus

# our own packages from victron
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService
from settingsdevice import SettingsDevice
from dbusmonitor import DbusMonitor

#formatting
_kwh = lambda p, v: (str(round(v, 2)) + 'KWh')
_a = lambda p, v: (str(round(v, 1)) + 'A')
_w = lambda p, v: (str(round(v, 1)) + 'W')
_v = lambda p, v: (str(round(v, 1)) + 'V')
_hz = lambda p, v: (str(round(v, 1)) + 'Hz')
_pct = lambda p, v: (str(round(v, 1)) + '%')
_c = lambda p, v: (str(round(v, 1)) + '°C')
_n = lambda p, v: (str(round(v, 1)))

class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)

def dbusconnection():
    return SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()

def new_service(base, type, physical, logical, id, instance):
    if instance == 0:
      self =  VeDbusService("{}.{}".format(base, type), dbusconnection())
    else:
      self =  VeDbusService("{}.{}.{}_id{:02d}".format(base, type, physical,  id), dbusconnection())
    # physical is the physical connection
    # logical is the logical connection to align with the numbering of the console display
    # Create the management objects, as specified in the ccgx dbus-api document
    self.add_path('/Mgmt/ProcessName', __file__)
    self.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
    self.add_path('/Mgmt/Connection', logical)

    # Create the mandatory objects, note these may need to be customised after object creation
    self.add_path('/DeviceInstance', instance)
    self.add_path('/ProductId', 0)
    self.add_path('/ProductName', '')
    self.add_path('/FirmwareVersion', 0)
    self.add_path('/HardwareVersion', 0)
    self.add_path('/Connected', 0)  # Mark devices as disconnected until they are confirmed
    self.add_path('/Serial', 0)

    return self


class DbusHmInverterService:
  def __init__(self):

    self.settings = None
    self.config = self._getConfig()
    self._powerMeterService = None
    self._inverterLoopCounter = 0
    self._powerLimitCounter = 0
    self._pvPowerAvg =  [0] * 20 * 15
    self._gridPowerAvg =  [0] * 6
    self._loadPowerHistory =  [600] * 60
    self._loadPowerMin = [600]*20

    self._inverterData = {}
    
    # Ahoy
    self._inverterData[0] = {}
    self._inverterData[0]['ch0/P_AC'] = 0
    self._inverterData[0]['ch0/U_AC'] = 0
    self._inverterData[0]['ch0/I_AC'] = 0
    self._inverterData[0]['ch0/P_DC'] = 0
    self._inverterData[0]['ch0/Freq'] = 0
    self._inverterData[0]['ch0/YieldTotal'] = 0
    self._inverterData[0]['ch1/U_DC'] = 0
    self._inverterData[0]['ch0/Efficiency'] = 0
    self._inverterData[0]['ch0/Temp'] = 0

    for i in range(1, 5):
      self._inverterData[0][f'ch{i}/I_DC'] = 0

    # OpenDTU
    self._inverterData[1] = {}
    self._inverterData[1]['0/power'] = 0
    self._inverterData[1]['0/voltage'] = 0
    self._inverterData[1]['0/current'] = 0
    self._inverterData[1]['0/powerdc'] = 0
    self._inverterData[1]['0/frequency'] = 0
    self._inverterData[1]['0/yieldtotal'] = 0
    self._inverterData[1]['1/voltage'] = 0
    self._inverterData[1]['0/efficiency'] = 0
    self._inverterData[1]['0/temperature'] = 0

    for i in range(1, 5):
      self._inverterData[1][f'ch{i}/current'] = 0

    self._dbus = dbusconnection()

    deviceinstance = int(self.config['DEFAULT']['Deviceinstance'])

    self._init_dbus_monitor()
    self._init_device_settings(deviceinstance)

    self._MQTTName = "{}-{}".format(self._dbusmonitor.get_value('com.victronenergy.system','/Serial'),deviceinstance) 
    self._inverterPath = self.settings['/InverterPath']
    self._devcontrolPath = '/'.join(self.settings['/InverterPath'].split('/')[:-1]) + "/devcontrol"

    self._MQTTconnected = 0
    self._init_MQTT()

    base = 'com.victronenergy'
    self._dbusservice = {}

    # Create VE.Bus inverter
    if self.settings['/DTU'] == 0:
      dtu = "Ahoy"
    else:
      dtu = "OpenDTU"

    self._dbusservice['vebus'] = new_service(base, 'vebus', 'DTU', dtu, deviceinstance, deviceinstance)

    # Init the inverter
    self._initInverter()

    self._refreshAcloads()

    # add _inverterLoop function 'timer'
    gobject.timeout_add(500, self._inverterLoop) # pause 5s before the next request

    # add _signOfLife 'timer' to get feedback in log every 5minutes
    gobject.timeout_add(self._getSignOfLifeInterval()*60*1000, self._signOfLife)


  def _initInverter(self):
    maxPower = self.settings['/MaxPower']

    paths = {
      '/Ac/ActiveIn/L1/V':                  {'initial': 0, 'textformat': _v},
      '/Ac/ActiveIn/L2/V':                  {'initial': 0, 'textformat': _v},
      '/Ac/ActiveIn/L3/V':                  {'initial': 0, 'textformat': _v},
      '/Ac/ActiveIn/L1/I':                  {'initial': 0, 'textformat': _a},
      '/Ac/ActiveIn/L2/I':                  {'initial': 0, 'textformat': _a},
      '/Ac/ActiveIn/L3/I':                  {'initial': 0, 'textformat': _a},
      '/Ac/ActiveIn/L1/F':                  {'initial': 0, 'textformat': _hz},
      '/Ac/ActiveIn/L2/F':                  {'initial': 0, 'textformat': _hz},
      '/Ac/ActiveIn/L3/F':                  {'initial': 0, 'textformat': _hz},
      '/Ac/ActiveIn/L1/P':                  {'initial': 0, 'textformat': _w},
      '/Ac/ActiveIn/L2/P':                  {'initial': 0, 'textformat': _w},
      '/Ac/ActiveIn/L3/P':                  {'initial': 0, 'textformat': _w},
      '/Ac/ActiveIn/P':                     {'initial': 0, 'textformat': _w},
      '/Ac/ActiveIn/Connected':             {'initial': 0, 'textformat': _n},
      '/Ac/Out/L1/V':                       {'initial': 0, 'textformat': _v},
      '/Ac/Out/L2/V':                       {'initial': 0, 'textformat': _v},
      '/Ac/Out/L3/V':                       {'initial': 0, 'textformat': _v},
      '/Ac/Out/L1/I':                       {'initial': 0, 'textformat': _a},
      '/Ac/Out/L2/I':                       {'initial': 0, 'textformat': _a},
      '/Ac/Out/L3/I':                       {'initial': 0, 'textformat': _a},
      '/Ac/Out/L1/F':                       {'initial': 0, 'textformat': _hz},
      '/Ac/Out/L2/F':                       {'initial': 0, 'textformat': _hz},
      '/Ac/Out/L3/F':                       {'initial': 0, 'textformat': _hz},
      '/Ac/Out/L1/P':                       {'initial': 0, 'textformat': _w},
      '/Ac/Out/L2/P':                       {'initial': 0, 'textformat': _w},
      '/Ac/Out/L3/P':                       {'initial': 0, 'textformat': _w},
      '/Ac/ActiveIn/ActiveInput':           {'initial': 0, 'textformat': _n},
      '/Ac/In/1/CurrentLimit':              {'initial': 0, 'textformat': _n},
      '/Ac/In/1/CurrentLimitIsAdjustable':  {'initial': 0, 'textformat': _n},
      '/Ac/In/2/CurrentLimit':              {'initial': 0, 'textformat': _n},
      '/Ac/In/2/CurrentLimitIsAdjustable':  {'initial': 0, 'textformat': _n},
      '/Settings/SystemSetup/AcInput1':     {'initial': 1, 'textformat': _n},
      '/Settings/SystemSetup/AcInput2':     {'initial': 0, 'textformat': _n},
      '/Ac/PowerMeasurementType':           {'initial': 4, 'textformat': _n},
      '/Ac/State/IgnoreAcIn1':              {'initial': 0, 'textformat': _n},
      '/Ac/State/IgnoreAcIn2':              {'initial': 0, 'textformat': _n},

      '/Ac/Power':                          {'initial': 0, 'textformat': _w},
      '/Ac/Efficiency':                     {'initial': 0, 'textformat': _pct},
      '/Ac/PowerLimit':                     {'initial': maxPower, 'textformat': _w},
      '/Ac/MaxPower':                       {'initial': maxPower, 'textformat': _w},
      '/Ac/Energy/Forward':                 {'initial': None,     'textformat': _kwh},

      '/Ac/NumberOfPhases':                 {'initial': 3, 'textformat': _n},
      '/Ac/NumberOfAcInputs':               {'initial': 1, 'textformat': _n},

      '/Alarms/HighDcCurrent':              {'initial': 0, 'textformat': _n},
      '/Alarms/HighDcVoltage':              {'initial': 0, 'textformat': _n},
      '/Alarms/LowBattery':                 {'initial': 0, 'textformat': _n},
      '/Alarms/PhaseRotation':              {'initial': 0, 'textformat': _n},
      '/Alarms/Ripple':                     {'initial': 0, 'textformat': _n},
      '/Alarms/TemperatureSensor':          {'initial': 0, 'textformat': _n},
      '/Alarms/L1/HighTemperature':         {'initial': 0, 'textformat': _n},
      '/Alarms/L1/LowBattery':              {'initial': 0, 'textformat': _n},
      '/Alarms/L1/Overload':                {'initial': 0, 'textformat': _n},
      '/Alarms/L1/Ripple':                  {'initial': 0, 'textformat': _n},
      '/Alarms/L2/HighTemperature':         {'initial': 0, 'textformat': _n},
      '/Alarms/L2/LowBattery':              {'initial': 0, 'textformat': _n},
      '/Alarms/L2/Overload':                {'initial': 0, 'textformat': _n},
      '/Alarms/L2/Ripple':                  {'initial': 0, 'textformat': _n},
      '/Alarms/L3/HighTemperature':         {'initial': 0, 'textformat': _n},
      '/Alarms/L3/LowBattery':              {'initial': 0, 'textformat': _n},
      '/Alarms/L3/Overload':                {'initial': 0, 'textformat': _n},
      '/Alarms/L3/Ripple':                  {'initial': 0, 'textformat': _n},

      '/Dc/0/Power':                        {'initial': 0, 'textformat': _w},
      '/Dc/0/Current':                      {'initial': 0, 'textformat': _a},
      '/Dc/0/Voltage':                      {'initial': 0, 'textformat': _v},
      '/Dc/0/Temperature':                  {'initial': 0, 'textformat': _n},

      '/Mode':                              {'initial': 0, 'textformat': _n},
      '/ModeIsAdjustable':                  {'initial': 1, 'textformat': _n},

      '/VebusChargeState':                  {'initial': 0, 'textformat': _n},
      '/VebusSetChargeState':               {'initial': 0, 'textformat': _n},

      '/Leds/Inverter':                     {'initial': 1, 'textformat': _n},

      '/Bms/AllowToCharge':                 {'initial': 0, 'textformat': _n},
      '/Bms/AllowToDischarge':              {'initial': 0, 'textformat': _n},
      '/Bms/BmsExpected':                   {'initial': 0, 'textformat': _n},
      '/Bms/Error':                         {'initial': 0, 'textformat': _n},

      '/Soc':                               {'initial': 0, 'textformat': _n},
      '/State':                             {'initial': 0, 'textformat': _n},
      '/RunState':                          {'initial': 0, 'textformat': _n},
      '/VebusError':                        {'initial': 0, 'textformat': _n},
      '/Temperature':                       {'initial': 0, 'textformat': _c},

      '/Hub4/L1/AcPowerSetpoint':           {'initial': 0, 'textformat': _n},
      '/Hub4/DisableCharge':                {'initial': 0, 'textformat': _n},
      '/Hub4/DisableFeedIn':                {'initial': 0, 'textformat': _n},
      '/Hub4/L2/AcPowerSetpoint':           {'initial': 0, 'textformat': _n},
      '/Hub4/L3/AcPowerSetpoint':           {'initial': 0, 'textformat': _n},
      '/Hub4/DoNotFeedInOvervoltage':       {'initial': 0, 'textformat': _n},
      '/Hub4/L1/MaxFeedInPower':            {'initial': 0, 'textformat': _n},
      '/Hub4/L2/MaxFeedInPower':            {'initial': 0, 'textformat': _n},
      '/Hub4/L3/MaxFeedInPower':            {'initial': 0, 'textformat': _n},
      '/Hub4/TargetPowerIsMaxFeedIn':       {'initial': 0, 'textformat': _n},
      '/Hub4/FixSolarOffsetTo100mV':        {'initial': 0, 'textformat': _n},
      '/Hub4/AssistantId':                  {'initial': 5, 'textformat': _n},

      '/PvInverter/Disable':                {'initial': 0, 'textformat': _n},
      '/SystemReset':                       {'initial': 0, 'textformat': _n},
      '/AvailableAcLoads':                  {'initial': '', 'textformat': None},
      '/Debug0':                            {'initial': 0, 'textformat': _n},
      '/Debug1':                            {'initial': 0, 'textformat': _n},
      '/Debug2':                            {'initial': 0, 'textformat': _n},
      '/Debug3':                            {'initial': 0, 'textformat': _n},
    }

    # add path values to dbus
    self._dbusservice['vebus'].add_path('/CustomName', self.settings['/Customname'], writeable=True, onchangecallback=self.customname_changed)
    for path, settings in paths.items():
      self._dbusservice['vebus'].add_path(
        path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)


    self._dbusservice['vebus']['/ProductId'] = 0xFFF1
    self._dbusservice['vebus']['/FirmwareVersion'] = 0x482
    self._dbusservice['vebus']['/ProductName'] = 'Hoymiles'
    self._dbusservice['vebus']['/Connected'] = 1


  def _handlechangedvalue(self, path, value):
    if path == '/Ac/PowerLimit':

      if self._dbusservice['vebus']['/RunState'] < 2 or self.settings['/LimitMode'] != 3:
        return False

      #logging.info("new power limit %s " % (value))
      self._inverterSetPower(value)

    return True # accept the change


  def customname_changed(self, path, val):
    self.settings['/Customname'] = val
    return True


  def _init_dbus_monitor(self):
    dummy = {'code': None, 'whenToLog': 'configChange', 'accessLevel': None}
    dbus_tree = {
      'com.victronenergy.settings': { # Not our settings
        '/Settings/CGwacs/BatteryLife/State': dummy,
      },
      'com.victronenergy.system': {
        '/Dc/Battery/Soc': dummy,
        '/Dc/Pv/Power': dummy,
        '/Ac/Consumption/L1/Power': dummy,
        '/Ac/Consumption/L2/Power': dummy,
        '/Ac/Consumption/L3/Power': dummy,
        '/Ac/Grid/L1/Power': dummy,
        '/Ac/Grid/L2/Power': dummy,
        '/Ac/Grid/L3/Power': dummy,
      },
      'com.victronenergy.hub4': {
        '/PvPowerLimiterActive': dummy,
      },
      'com.victronenergy.acload': {
        '/Ac/Power': dummy,
        '/CustomName': dummy,
        '/ProductName': dummy,
        '/DeviceInstance': dummy,
        '/Connected': dummy,
      },
    }
    self._dbusmonitor = DbusMonitor(dbus_tree, valueChangedCallback=self._dbusValueChanged, deviceAddedCallback= self._dbusDeviceAdded, deviceRemovedCallback=self._dbusDeviceRemoved)


  def _dbusValueChanged(self, dbusServiceName, dbusPath, options, changes, deviceInstance):
    try:

      if dbusPath in {'/Dc/Battery/Soc','/Settings/CGwacs/BatteryLife/State','/Hub','/PvPowerLimiterActive'}:
        logging.info("dbus_value_changed: %s %s %s" % (dbusServiceName, dbusPath, changes['Value']))

      elif dbusPath == '/Connected':
        self._refreshAcloads()

    except Exception as e:
      logging.critical('Error at %s', '_dbus_value_changed', exc_info=e)

    return

    
  def _dbusDeviceAdded(self, dbusservicename, instance):
    logging.info("dbus_device_added: %s %s " % (dbusservicename, instance))
    self._refreshAcloads()

    return


  def _dbusDeviceRemoved(self, dbusservicename, instance):
    logging.info("dbus_device_removed: %s %s " % (dbusservicename, instance))
    self._refreshAcloads()

    return


  def _refreshAcloads(self):
    availableAcLoads = []
    powerMeterService = None
    deviceName = ''

    for service in self._dbusmonitor.get_service_list('com.victronenergy.acload'):
      logging.debug("acload: %s %s %s" % (service, self._dbusmonitor.get_value(service,'/CustomName'), self._dbusmonitor.get_value(service,'/DeviceInstance')))
      if self._dbusmonitor.get_value(service,'/CustomName') == None:
        deviceName = self._dbusmonitor.get_value(service,'/ProductName')
      else:
        deviceName = self._dbusmonitor.get_value(service,'/CustomName')

      availableAcLoads.append(deviceName+':'+str(self._dbusmonitor.get_value(service,'/DeviceInstance')))
      if self._dbusmonitor.get_value(service,'/DeviceInstance') == self.settings['/PowerMeterInstance'] and self._dbusmonitor.get_value(service,'/Connected') == 1:
         powerMeterService = service
      
    self._powerMeterService = powerMeterService
    self._dbusservice['vebus']['/AvailableAcLoads'] = availableAcLoads #separator.join(availableAcLoads)



  def _init_device_settings(self, deviceinstance):
    if self.settings:
        return

    path = '/Settings/DTU/{}'.format(deviceinstance)

    SETTINGS = {
        '/Customname':                    [path + '/CustomName', 'HM-600', 0, 0],
        '/MaxPower':                      [path + '/MaxPower', 600, 0, 0],
        '/Phase':                         [path + '/Phase', 1, 1, 3],
        '/PowerMeterInstance':            [path + '/PowerMeterInstance', 0, 0, 0],
        '/MqttUrl':                       [path + '/MqttUrl', '127.0.0.1', 0, 0],
        '/InverterPath':                  [path + '/InverterPath', 'inverter/HM-600', 0, 0],
        '/DTU':                           [path + '/DTU', 0, 0, 1],
        '/StartLimit':                    [path + '/StartLimit', 0, 0, 1],
        '/LimitMode':                     [path + '/LimitMode', 0, 0, 2],
        '/GridTargetDevMin':              [path + '/GridTargetDevMin', 25, 5, 100],
        '/GridTargetDevMax':              [path + '/GridTargetDevMax', 25, 5, 100],
        '/GridTargetPower':               [path + '/GridTargetPower', 25, -100, 200],
        '/GridTargetInterval':            [path + '/GridTargetInterval', 15, 3, 60],
        '/BaseLoadPeriod':                [path + '/BaseLoadPeriod', 0.5, 0.5, 10],
        '/Settings/SystemSetup/AcInput1': ['/Settings/SystemSetup/AcInput1', 1, 0, 1],
        '/Settings/SystemSetup/AcInput2': ['/Settings/SystemSetup/AcInput2', 0, 0, 1],
    }

    self.settings = SettingsDevice(self._dbus, SETTINGS, self._setting_changed)


  def _setting_changed(self, setting, oldvalue, newvalue):
    logging.info("setting changed, setting: %s, old: %s, new: %s" % (setting, oldvalue, newvalue))

    if setting == '/Customname':
      self._dbusservice['vebus']['/CustomName'] = newvalue

    elif setting == '/MaxPower':
      self._dbusservice['vebus']['/Ac/MaxPower'] = newvalue
      if self.settings['/LimitMode'] == 0:
        self._inverterSetLimit(newvalue)

    elif setting == '/LimitMode' and newvalue == 0:
      self._inverterSetLimit(self.settings['/MaxPower'])
      
    elif setting == '/InverterPath':
      self._inverterPath = newvalue
      self._devcontrolPath = '/'.join(newvalue.split('/')[:-1]) + "/devcontrol"
      try:
        self._MQTTclient.connect(self.settings['/MqttUrl'])
      except Exception as e:
        logging.exception("Fehler beim connecten mit Broker")
        self._MQTTconnected = 0
    
    elif setting == '/MqttUrl':
      try:
        self._MQTTclient.connect(newvalue)
      except Exception as e:
        logging.exception("Fehler beim connecten mit Broker")
        self._MQTTconnected = 0

    elif setting == '/StartLimit':
      self._checkInverterState()

    elif setting == '/DTU':
      if self.settings['/DTU'] == 0:
        self._dbusservice['vebus']['/Mgmt/Connection'] = "Ahoy"
      else:
        self._dbusservice['vebus']['/Mgmt/Connection'] = "OpenDTU"
      try:
        self._MQTTclient.connect(self.settings['/MqttUrl'])
      except Exception as e:
        logging.exception("Fehler beim connecten mit Broker")
        self._MQTTconnected = 0

    elif setting == '/PowerMeterInstance':
      self._refreshAcloads()


  def _checkInverterState(self):
    if self._dbusservice['vebus']['/RunState'] == 0: # Inverter is switched off

      # Switch on inverter if self consumption is allowed
      if self._batteryLifeIsSelfConsumption() == True:
        if self.settings['/StartLimit'] == 1:
          self._dbusservice['vebus']['/Ac/MaxPower'] = 100
        else:
          self._dbusservice['vebus']['/Ac/MaxPower'] = self.settings['/MaxPower']
        self._inverterSetLimit(self._dbusservice['vebus']['/Ac/MaxPower'])
        self._dbusservice['vebus']['/RunState'] = 1
        return

      # Switch off inverter again if it is still running
      if self._dbusservice['vebus']['/Ac/Power'] > 0:
        self._inverterOff()

    else: # Inverter is switched on

      if  self._dbusservice['vebus']['/RunState'] == 1: # Start inverter
        if self._dbusservice['vebus']['/Ac/Power'] == 0:
          self._inverterOn()
        else:
          self._dbusservice['vebus']['/RunState'] = 2
          self._checkStartLimit(True)
        self._dbusservice['vebus']['/State'] = 9
        return

      if  self._dbusservice['vebus']['/RunState'] == 2: # Inverter is switched on with start limit
        self._checkStartLimit(False)

      # Switch off inverter if SOC is below limit
      if self._batteryLifeIsSelfConsumption() == False or self._dbusmonitor.get_value('com.victronenergy.system','/Dc/Battery/Soc') == 5:
        self._inverterOff()
        self._dbusservice['vebus']['/RunState'] = 0
        return


  def _checkStartLimit(self, startup):
    if self.settings['/StartLimit'] == 1:
      # Calculate the new power limit
      pvPowerAverage = sum(self._pvPowerAvg) / len(self._pvPowerAvg)
      newLimit = int((pvPowerAverage * 0.95) / 10) * 10

      if startup == True and newLimit == 0:
        # No PV power, start without limit
        self._dbusservice['vebus']['/RunState'] = 3

      if newLimit > self.settings['/MaxPower']:
        # Power limit is higher than maximum inverter power, switch off start limit
        self._dbusservice['vebus']['/RunState'] = 3
        logging.info("Start limit off")

      elif self._dbusservice['vebus']['/Ac/MaxPower'] < newLimit:
        # Increase start limit
        logging.info("Start limit: %i" % (newLimit))
        self._dbusservice['vebus']['/Ac/MaxPower'] = newLimit

        if self.settings['/LimitMode'] == 0:
          self._inverterSetLimit(newLimit)

    else:
      self._dbusservice['vebus']['/RunState'] = 3
      logging.info("Start limit off")

    if self._dbusservice['vebus']['/RunState'] == 3:
      self._dbusservice['vebus']['/Ac/MaxPower'] = self.settings['/MaxPower']

      if self.settings['/LimitMode'] == 0:
        self._inverterSetLimit(self.settings['/MaxPower'])


  def _batteryLifeIsSelfConsumption(self):
    # Optimized mode with BatteryLife:
    # 1: Value set by the GUI when BatteryLife is enabled. Hub4Control uses it to find the right BatteryLife #   state (values 2-7) based on system state
    # 2: Self consumption
    # 3: Self consumption, SoC exceeds 85%
    # 4: Self consumption, SoC at 100%
    # 5: SoC below BatteryLife dynamic SoC limit
    # 6: SoC has been below SoC limit for more than 24 hours. Charging with battery with 5amps
    # 7: Multi/Quattro is in sustain
    # 8: Recharge, SOC dropped 5% or more below MinSOC.
    if self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/BatteryLife/State') in (2, 3, 4):
      return True

    # Keep batteries charged mode:
    # 9: 'Keep batteries charged' mode enabled
    if self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/BatteryLife/State') == 9 \
    and self._dbusmonitor.get_value('com.victronenergy.system','/Dc/Battery/Soc') > 95 and self._dbusservice['vebus']['/RunState'] > 0:
      return True

    if self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/BatteryLife/State') == 9 \
    and self._dbusmonitor.get_value('com.victronenergy.system','/Dc/Battery/Soc') == 100:
      return True

    # Optimized mode without BatteryLife:
    # 10: Self consumption, SoC at or above minimum SoC
    # 11: Self consumption, SoC is below minimum SoC
    # 12: Recharge, SOC dropped 5% or more below minimum SoC
    if self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/BatteryLife/State') == 10:
      return True

    return False


  def _inverterOn(self):
    logging.info("Inverter On ")
    if self.settings['/DTU'] == 0:
      # Ahoy
      self._MQTTclient.publish(self._devcontrolPath + '/0/0', 1)
    else:
      # OpenDTU
        self._MQTTclient.publish(self._inverterPath + '/cmd/power', 1)
    

  def _inverterOff(self):
    logging.info("Inverter Off ")
    if self.settings['/DTU'] == 0:
      # Ahoy
      self._MQTTclient.publish(self._devcontrolPath + '/0/1', 1)
    else:
      # OpenDTU
        self._MQTTclient.publish(self._inverterPath + '/cmd/power', 0)

    self._dbusservice['vebus']['/State'] = 0


  def _inverterSetLimit(self, newLimit):
    self._inverterSetPower(newLimit, False)
    self._dbusservice['vebus']['/Ac/PowerLimit'] = newLimit


  def _inverterSetPower(self, power, force=False):
    newPower      = int(power)
    currentPower  = int(self._dbusservice['vebus']['/Ac/PowerLimit'] )

    if newPower < 25:
      newPower = 25

    if newPower != currentPower or force == True:
      if self.settings['/DTU'] == 0:
        # Ahoy
        self._MQTTclient.publish(self._devcontrolPath + '/0/11', newPower)
      else:
        # OpenDTU
         self._MQTTclient.publish(self._inverterPath + '/cmd/limit_nonpersistent_absolute', newPower)
      
      self._powerLimitCounter = 0


  def _inverterLoop(self):
    try:
      # 0.5s interval
      self._inverterLoopCounter +=1
      self._inverterUpdate()
      self._powerLimitCounter +=1

      gridPower = self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Grid/L1/Power') + \
                  self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Grid/L2/Power') + \
                  self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Grid/L3/Power')
      loadPower = self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Consumption/L1/Power') + \
                  self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Consumption/L2/Power') + \
                  self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Consumption/L3/Power')

      self._gridPowerAvg.pop(0)
      self._gridPowerAvg.append(gridPower)

      self._loadPowerHistory.pop(len(self._loadPowerHistory)-1)
      self._loadPowerHistory.insert(0,loadPower)


      if self._dbusservice['vebus']['/RunState'] >= 2:

        # Grid target limit mode
        if self.settings['/LimitMode'] == 1 and self._powerLimitCounter >= self.settings['/GridTargetInterval'] * 2:
          if gridPower < self.settings['/GridTargetPower'] - self.settings['/GridTargetDevMin'] \
          or gridPower > self.settings['/GridTargetPower'] + self.settings['/GridTargetDevMax']:

            if gridPower < self.settings['/GridTargetPower'] - 2 * self.settings['/GridTargetDevMin']:
                gridPowerTarget = gridPower
            else:
                gridPowerTarget = sum(self._gridPowerAvg) / len(self._gridPowerAvg)

            newTarget = self._dbusservice['vebus']['/Ac/Power'] + gridPowerTarget
            newTarget = min(newTarget - self.settings['/GridTargetPower'] , self._dbusservice['vebus']['/Ac/MaxPower'])
            newTarget = max(newTarget, 25)
            self._inverterSetLimit(newTarget)

        # Base load limit mode
        if self.settings['/LimitMode'] == 2 and gridPower < 0 and self._powerLimitCounter >= 10:
          newTarget1 = min(self._loadPowerHistory)
          newTarget2 = min(self._loadPowerMin[0:int(self.settings['/BaseLoadPeriod'] * 2)])
          newTarget = min(newTarget1, newTarget2) - 10
          newTarget = min(newTarget, self._dbusservice['vebus']['/Ac/MaxPower'])
          newTarget = max(newTarget, 25)
          self._inverterSetLimit(newTarget)
          #logging.info("new base limit %s " % (newTarget))

      #5s interval
      if self._inverterLoopCounter % 10 == 0:
        self._pvPowerAvg.pop(0)
        self._pvPowerAvg.append(self._dbusmonitor.get_value('com.victronenergy.system','/Dc/Pv/Power') or 0)

      # 20s interval
      if self._inverterLoopCounter % 40 == 0:
        self._checkInverterState()

      # 30s interval
      if self._inverterLoopCounter % 60 == 0:
        self._loadPowerMin.pop(len(self._loadPowerMin)-1)
        self._loadPowerMin.insert(0,min(self._loadPowerHistory))

        if self._dbusservice['vebus']['/RunState'] >= 2 and self.settings['/LimitMode'] == 2:
          newTarget = min(self._loadPowerMin[0:int(self.settings['/BaseLoadPeriod'] * 2)]) - 10
          newTarget = min(newTarget, self._dbusservice['vebus']['/Ac/MaxPower'])
          newTarget = max(newTarget, 25)
          self._inverterSetLimit(newTarget)
          #print(self._loadPowerMin[0:(self.settings['/BaseLoadPeriod'] * 2)])

          self._dbusservice['vebus']['/Debug0'] = self._loadPowerMin[0]
          self._dbusservice['vebus']['/Debug1'] = newTarget


      # 5min interval
      if self._inverterLoopCounter % 600 == 0:
        self._inverterLoopCounter = 0

        if self._dbusservice['vebus']['/RunState'] > 1:
          self._inverterSetPower(self._dbusservice['vebus']['/Ac/PowerLimit'], True)

    except Exception as e:
      logging.critical('Error at %s', '_inverterLoop', exc_info=e)

    return True


  def _inverterUpdate(self):
    try:

      pvinverter_phase = 'L' + str(self.settings['/Phase'])

      if self._powerMeterService != None:
        powerAC =  self._dbusmonitor.get_value(self._powerMeterService,'/Ac/Power') or 0
      elif self.settings['/DTU'] == 0:
        powerAC = self._inverterData[0]['ch0/P_AC']
      else:
        powerAC = self._inverterData[1]['0/power']

      if self.settings['/DTU'] == 0:
        # Ahoy
        voltageAC   = self._inverterData[0]['ch0/U_AC']
        currentAC   = self._inverterData[0]['ch0/I_AC']
        frequency   = self._inverterData[0]['ch0/Freq']
        yieldTotal  = self._inverterData[0]['ch0/YieldTotal']
        efficiency  = self._inverterData[0]['ch0/Efficiency']
        volatageDC  = self._inverterData[0]['ch1/U_DC']
        powerDC     = self._inverterData[0]['ch0/P_DC']
        temperature = self._inverterData[0]['ch0/Temp']
        currentDC = 0
        for i in range(1, 5):
          currentDC -= self._inverterData[0][f'ch{i}/I_DC']
      else:
        # OpenDTU
        voltageAC   = self._inverterData[1]['0/voltage']
        currentAC   = self._inverterData[1]['0/current']
        frequency   = self._inverterData[1]['0/frequency']
        yieldTotal  = self._inverterData[1]['0/yieldtotal']
        efficiency  = self._inverterData[1]['0/efficiency']
        volatageDC  = self._inverterData[1]['1/voltage']
        powerDC     = self._inverterData[1]['0/powerdc']
        temperature = self._inverterData[1]['0/temperature']
        currentDC = 0
        for i in range(1, 5):
          currentDC -= self._inverterData[1][f'ch{i}/current']

      #send data to DBus
      for phase in ['L1', 'L2', 'L3']:
        pre = '/Ac/ActiveIn/' + phase

        if phase == pvinverter_phase:
          self._dbusservice['vebus'][pre + '/V'] = voltageAC
          self._dbusservice['vebus'][pre + '/I'] = currentAC
          self._dbusservice['vebus'][pre + '/P'] = 0-powerAC
          self._dbusservice['vebus'][pre + '/F'] = frequency

        else:
          self._dbusservice['vebus'][pre + '/V'] = 0
          self._dbusservice['vebus'][pre + '/I'] = 0
          self._dbusservice['vebus'][pre + '/P'] = 0
          self._dbusservice['vebus'][pre + '/F'] = 0

      self._dbusservice['vebus']['/Ac/Power'] = powerAC
      self._dbusservice['vebus']['/Ac/ActiveIn/P'] = 0-powerAC
      self._dbusservice['vebus']['/Ac/Energy/Forward'] = yieldTotal
      self._dbusservice['vebus']['/Ac/Efficiency'] = efficiency

      self._dbusservice['vebus']['/Dc/0/Current'] = currentDC
      self._dbusservice['vebus']['/Dc/0/Voltage'] = volatageDC
      self._dbusservice['vebus']['/Dc/0/Power'] = powerDC

      self._dbusservice['vebus']['/Temperature'] = temperature

    except Exception as e:
      logging.critical('Error at %s', '_update', exc_info=e)

    return True


  def _getConfig(self):
    config = configparser.ConfigParser()
    config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
    return config;


  def _getSignOfLifeInterval(self):
    value = self.config['DEFAULT']['SignOfLifeLog']

    if not value:
        value = 0

    return int(value)


  def _signOfLife(self):

    logging.info("'/Ac/Power': %s  'Soc': %s  'BLS': %s  'PvAvg': %i" % (
      self._dbusservice['vebus']['/Ac/Power'],
      self._dbusmonitor.get_value('com.victronenergy.system','/Dc/Battery/Soc'),
      self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/BatteryLife/State'),
      sum(self._pvPowerAvg) / len(self._pvPowerAvg)
      ))

    return True


  def _init_MQTT(self):
    self._MQTTclient = mqtt.Client(self._MQTTName) # create new instance
    self._MQTTclient.on_disconnect = self._on_MQTT_disconnect
    self._MQTTclient.on_connect = self._on_MQTT_connect
    self._MQTTclient.on_message = self._on_MQTT_message
    try:
      self._MQTTclient.connect(self.settings['/MqttUrl'])  # connect to broker
      self._MQTTclient.loop_start()
    except Exception as e:
      logging.exception("Fehler beim connecten mit Broker")
      self._MQTTconnected = 0

  def _on_MQTT_disconnect(self, client, userdata, rc):
    print("Client Got Disconnected")
    if rc != 0:
        print('Unexpected MQTT disconnection. Will auto-reconnect')

    else:
        print('rc value:' + str(rc))

    try:
        print("Trying to Reconnect")
        client.connect(self.settings['/MqttUrl'])
        self._MQTTconnected = 1
    except Exception as e:
        logging.exception("Fehler beim reconnecten mit Broker")
        print("Error in Retrying to Connect with Broker")
        self._MQTTconnected = 0
        print(e)


  def _on_MQTT_connect(self, client, userdata, flags, rc):
    if rc == 0:
        self._MQTTconnected = 1

        for k,v in self._inverterData[self.settings['/DTU']].items():
          client.subscribe(f'{self._inverterPath}/{k}')

    else:
        print("Failed to connect, return code %d\n", rc)


  def _on_MQTT_message(self, client, userdata, msg):
      try:
          for k,v in self._inverterData[self.settings['/DTU']].items():
            if msg.topic == f'{self._inverterPath}/{k}':
              self._inverterData[self.settings['/DTU']][k] = float(msg.payload)
              return

      except Exception as e:
          logging.critical('Error at %s', '_update', exc_info=e)


def main():
  #configure logging
  logging.basicConfig(      format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S',
                            level=logging.INFO,
                            handlers=[
                                logging.FileHandler("%s/current.log" % (os.path.dirname(os.path.realpath(__file__)))),
                                logging.StreamHandler()
                            ])
  thread.daemon = True # allow the program to quit

  try:
      logging.info("Start")

      from dbus.mainloop.glib import DBusGMainLoop
      # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
      DBusGMainLoop(set_as_default=True)

      #start our main-service
      pvac_output = DbusHmInverterService()

      logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
      mainloop = gobject.MainLoop()
      mainloop.run()

  except Exception as e:
    logging.critical('Error at %s', 'main', exc_info=e)



if __name__ == "__main__":
  main()
