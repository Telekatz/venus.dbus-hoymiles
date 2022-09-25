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
    self._shelly = False
    self._inverterLoopCounter = 0
    self._powerLimitCounter = 0
    self._pvPowerAvg =  [0] * 20 * 15
    self._gridPowerAvg =  [0] * 6

    self._inverterData = {}
    self._inverterData['ch0/P_AC'] = 0 
    self._inverterData['ch0/U_AC'] = 0 
    self._inverterData['ch0/I_AC'] = 0
    self._inverterData['ch0/P_DC'] = 0     
    self._inverterData['ch0/YieldTotal'] = 0 
    self._inverterData['ch1/U_DC'] = 0
    
    for i in range(1, 5):
      self._inverterData[f'ch{i}/I_DC'] = 0        
    
    self._dbusData = {'Soc':0, 'BatteryLifeState':0, 'Hub':0, 'DcPvPower':0,  'GridPower':0, 'PvPowerLimiterActive':0 }
    self._dbus = dbusconnection()
    
    deviceinstance = int(self.config['DEFAULT']['Deviceinstance'])
    
    self._init_dbus_monitor()
    self._init_device_settings(deviceinstance) 
    
    self._brokerAddress = self.config['MQTT']['BrokerAddress']
    self._MQTTName = self.config['MQTT']['MQTTName']
    self._inverterPath = self.settings['/InverterPath']
    self._devcontrolPath = '/'.join(self.settings['/InverterPath'].split('/')[:-1]) + "/devcontrol"
    
    self._MQTTconnected = 0
    self._init_MQTT()
    
    base = 'com.victronenergy'
    self._dbusservice = {}
    
    # Create a dummy VE.Bus inverter to activate the ESS assistant.
    self._dbusservice['vebus']        = new_service(base, 'vebus', 'MQTT', 'AHOY-DTU', 99, 99)
    
    # Create the Hoymiles inverter
    self._dbusservice['pvinverter']   = new_service(base, 'pvinverter', 'MQTT', 'AHOY-DTU', deviceinstance, deviceinstance)
    
    # Init the inverters
    self._initHmInverter()   
    self._initDummyInverter()
    
    #Check if settings for Shelly are valid
    if self.settings['/Shelly/Enable'] == 1:
      self._checkShelly()
        
    # add _inverterLoop function 'timer'
    gobject.timeout_add(500, self._inverterLoop) # pause 5s before the next request
    
    # add _signOfLife 'timer' to get feedback in log every 5minutes
    gobject.timeout_add(self._getSignOfLifeInterval()*60*1000, self._signOfLife)
  

  def _initHmInverter(self):
    maxPower = self.settings['/MaxPower']
    
    paths = {
      '/Ac/Energy/Forward':     {'initial': None,     'textformat': _kwh},
      '/Ac/Power':              {'initial': 0,        'textformat': _w},
      '/Ac/Current':            {'initial': 0,        'textformat': _a},
      '/Ac/Voltage':            {'initial': 0,        'textformat': _v},
      '/Ac/L1/Voltage':         {'initial': 0,        'textformat': _v},
      '/Ac/L2/Voltage':         {'initial': 0,        'textformat': _v},
      '/Ac/L3/Voltage':         {'initial': 0,        'textformat': _v},
      '/Ac/L1/Current':         {'initial': 0,        'textformat': _a},
      '/Ac/L2/Current':         {'initial': 0,        'textformat': _a},
      '/Ac/L3/Current':         {'initial': 0,        'textformat': _a},
      '/Ac/L1/Power':           {'initial': 0,        'textformat': _w},
      '/Ac/L2/Power':           {'initial': 0,        'textformat': _w},
      '/Ac/L3/Power':           {'initial': 0,        'textformat': _w},
      '/Ac/L1/Energy/Forward':  {'initial': None,     'textformat': _kwh},
      '/Ac/L2/Energy/Forward':  {'initial': None,     'textformat': _kwh},
      '/Ac/L3/Energy/Forward':  {'initial': None,     'textformat': _kwh},
      '/Ac/PowerLimit':         {'initial': maxPower, 'textformat': _w},
      '/Ac/MaxPower':           {'initial': maxPower, 'textformat': _w},
      '/Dc/Power':              {'initial': 0,        'textformat': _w},
      '/Dc/Current':            {'initial': 0,        'textformat': _a},
      '/Dc/Voltage':            {'initial': 0,        'textformat': _v},
      '/StatusCode':            {'initial': 7,        'textformat': _n},
      '/ErrorCode':             {'initial': 0,        'textformat': _n},
      '/Position':              {'initial': 0,        'textformat': _n},
      '/State':                 {'initial': 0,        'textformat': _n},
    }

    # add path values to dbus
    self._dbusservice['pvinverter'].add_path('/CustomName', self.get_customname(), writeable=True, onchangecallback=self.customname_changed)
    for path, settings in paths.items():
      self._dbusservice['pvinverter'].add_path(
        path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)
    
    self._dbusservice['pvinverter']['/ProductName'] = 'HM-600'
    self._dbusservice['pvinverter']['/Connected'] = 1
    self._dbusservice['pvinverter']['/ProductId'] = 0xFFF1
    self._dbusservice['pvinverter']['/FirmwareVersion'] = 999
  
  
  def _initDummyInverter(self):
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
      '/VebusError':                        {'initial': 0, 'textformat': _n},
      
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
    }
    
    # add path values to dbus
    self._dbusservice['vebus'].add_path('/CustomName', 'Dummy')
    for path, settings in paths.items():
      self._dbusservice['vebus'].add_path(
        path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)
    
    
    self._dbusservice['vebus']['/ProductId'] = 0x2644
    self._dbusservice['vebus']['/FirmwareVersion'] = 0x482
    self._dbusservice['vebus']['/ProductName'] = 'Dummy Quattro'
    self._dbusservice['vebus']['/Connected'] = 1  
    
  
  def _init_dbus_monitor(self):
    dummy = {'code': None, 'whenToLog': 'configChange', 'accessLevel': None}
    dbus_tree = {
      'com.victronenergy.settings': { # Not our settings
        '/Settings/CGwacs/BatteryLife/SocLimit': dummy,
        '/Settings/CGwacs/BatteryLife/State': dummy,
      },
      'com.victronenergy.system': {
        '/Dc/Battery/Soc': dummy,
        '/Hub': dummy,
        '/Dc/Pv/Power': dummy,
      },
      'com.victronenergy.grid': {
        '/Ac/Power': dummy,
      },
      'com.victronenergy.hub4': {
        '/PvPowerLimiterActive': dummy,
      },
    }
    self._dbusmonitor = DbusMonitor(dbus_tree, valueChangedCallback=self._dbus_value_changed)
    
    self._dbusData['Soc'] = self._dbus.get_object('com.victronenergy.system', '/Dc/Battery/Soc').GetValue()
    self._dbusData['BatteryLifeState'] = self._dbus.get_object('com.victronenergy.settings', '/Settings/CGwacs/BatteryLife/State').GetValue()
    self._dbusData['Hub'] = self._dbus.get_object('com.victronenergy.system', '/Hub').GetValue()
    self._dbusData['PvPowerLimiterActive'] = self._dbus.get_object('com.victronenergy.hub4', '/PvPowerLimiterActive').GetValue()
  

  def _dbus_value_changed(self, dbusServiceName, dbusPath, options, changes, deviceInstance):
    try:        
      if dbusPath == '/Dc/Pv/Power':
        self._dbusData['DcPvPower'] = int(changes['Value'])               
        return
      
      if dbusPath == '/Ac/Power':
        self._dbusData['GridPower'] = int(changes['Value'])               
        return

      elif dbusPath == '/Dc/Battery/Soc':
        self._dbusData['Soc'] = int(changes['Value'])
      
      elif dbusPath == '/Settings/CGwacs/BatteryLife/State':
        self._dbusData['BatteryLifeState'] = int(changes['Value'])
      
      elif dbusPath == '/Hub':
        self._dbusData['Hub'] = int(changes['Value'])

      elif dbusPath == '/PvPowerLimiterActive':
        self._dbusData['PvPowerLimiterActive'] = int(changes['Value'])
        self._inverterSetLimit(self.settings['/MaxPower'])

      else:
        return
      
      logging.info("dbus_value_changed: %s %s %s" % (dbusServiceName, dbusPath, changes['Value']))
    
    except Exception as e:
      logging.critical('Error at %s', '_dbus_value_changed', exc_info=e)
      
    return
  
  
  def _handlechangedvalue(self, path, value):
    if path == '/Ac/PowerLimit':
      
      if self._dbusservice['pvinverter']['/State'] < 2 or self.settings['/ZeroFeedInMode'] > 0:
        return False
      
      #logging.info("new power limit %s " % (value))
      self._inverterSetPower(value)
        
    return True # accept the change
    
  
  def _init_device_settings(self, deviceinstance):
    if self.settings:
        return
        
    path = '/Settings/Ahoy/{}'.format(deviceinstance)

    SETTINGS = {
        '/Customname':          [path + '/CustomName', 'HM-600', 0, 0],
        '/MaxPower':            [path + '/MaxPower', 600, 0, 0],
        '/Phase':               [path + '/Phase', 1, 1, 3],
        '/Shelly/Enable':       [path + '/Shelly/Enable', 0, 0, 1],
        '/Shelly/PowerMeter':   [path + '/Shelly/PowerMeter', 0, 0, 1],
        '/Shelly/Url':          [path + '/Shelly/Url', '192.168.69.1', 0, 0],
        '/Shelly/User':         [path + '/Shelly/Username', '', 0, 0],
        '/Shelly/Pwd':          [path + '/Shelly/Password', '', 0, 0],
        '/InverterPath':        [path + '/InverterPath', 'inverter/HM-600', 0, 0],
        '/StartLimit':          [path + '/StartLimit', 0, 0, 1],
        '/ZeroFeedInMode':      [path + '/ZeroFeedInMode', 1, 0, 1],
        '/ZeroFeedInMin':       [path + '/ZeroFeedInMin', 25, 5, 100],
        '/ZeroFeedInMax':       [path + '/ZeroFeedInMax', 25, 5, 100],
        '/ZeroFeedInTarget':    [path + '/ZeroFeedInTarget', 25, -100, 200],
        '/ZeroFeedInInterval':  [path + '/ZeroFeedInInterval', 15, 3, 60],
    }

    self.settings = SettingsDevice(self._dbus, SETTINGS, self._setting_changed)
    
  
  def _setting_changed(self, setting, oldvalue, newvalue):
    logging.info("setting changed, setting: %s, old: %s, new: %s" % (setting, oldvalue, newvalue))
    
    if setting == '/Customname':
      self._dbusservice['pvinverter']['/CustomName'] = newvalue
      return
    
    if setting == '/MaxPower':
      self._dbusservice['pvinverter']['/Ac/MaxPower'] = newvalue
      if self._dbusData['PvPowerLimiterActive'] == 0:
        self._inverterSetLimit(newvalue)
      return
    
    if 'Shelly' in setting:
      self._checkShelly()
    
    if setting == '/InverterPath':
      self._inverterPath = newvalue
      self._devcontrolPath = '/'.join(newvalue.split('/')[:-1]) + "/devcontrol"
      self._MQTTclient.connect(self._brokerAddress)
    
    if setting == '/StartLimit':
      self._checkInverterState()

  def get_customname(self):
    return self.settings['/Customname']


  def customname_changed(self, path, val):
    self.settings['/Customname'] = val
    return True
  

  def _checkInverterState(self):
    if self._dbusservice['pvinverter']['/State'] == 0: # Inverter is switched off
      
      # Switch on inverter if self consumption is allowed
      if self._batteryLifeIsSelfConsumption() == True:
        if self.settings['/StartLimit'] == 1:
          self._dbusservice['pvinverter']['/Ac/MaxPower'] = 100
        else:
          self._dbusservice['pvinverter']['/Ac/MaxPower'] = self.settings['/MaxPower']
        self._inverterSetLimit(self._dbusservice['pvinverter']['/Ac/MaxPower'])
        self._dbusservice['pvinverter']['/State'] = 1
        return
      
      # Switch off inverter again if it is still running       
      if self._inverterData['ch0/P_AC'] > 0:
        self._inverterOff()
    
    else: # Inverter is switched on 

      if  self._dbusservice['pvinverter']['/State'] == 1: # Start inverter
        if self._inverterData['ch0/P_AC'] == 0:
          self._inverterOn()
        else:
          self._dbusservice['pvinverter']['/State'] = 2
          self._checkStartLimit(True)
        return

      if  self._dbusservice['pvinverter']['/State'] == 2: # Inverter is switched on with start limit
        self._checkStartLimit(False)

      # Switch off inverter if SOC is below limit
      if self._batteryLifeIsSelfConsumption() == False or self._dbusData['Soc'] == 5:
        self._inverterOff()
        self._dbusservice['pvinverter']['/State'] = 0
        return
  
  
  def _checkStartLimit(self, startup):
    if self.settings['/StartLimit'] == 1: 
      # Calculate the new power limit
      pvPowerAverage = sum(self._pvPowerAvg) / len(self._pvPowerAvg)
      newLimit = int((pvPowerAverage * 0.95) / 10) * 10

      if startup == True and newLimit == 0:
        # No PV power, start without limit
        self._dbusservice['pvinverter']['/State'] = 3
      
      if newLimit > self.settings['/MaxPower']:
        # Power limit is higher than maximum inverter power, switch off start limit
        self._dbusservice['pvinverter']['/State'] = 3
        logging.info("Start limit off")

      elif self._dbusservice['pvinverter']['/Ac/MaxPower'] < newLimit:
        # Increase start limit
        logging.info("Start limit: %i" % (newLimit))
        self._dbusservice['pvinverter']['/Ac/MaxPower'] = newLimit
        
        if self._dbusData['PvPowerLimiterActive'] == 0:
          self._inverterSetLimit(newLimit)
    
    else:
      self._dbusservice['pvinverter']['/State'] = 3
      logging.info("Start limit off")
      
    if self._dbusservice['pvinverter']['/State'] == 3:
      self._dbusservice['pvinverter']['/Ac/MaxPower'] = self.settings['/MaxPower']
      
      if self._dbusData['PvPowerLimiterActive'] == 0:
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
    if self._dbusData['BatteryLifeState'] >= 2 and self._dbusData['BatteryLifeState'] <= 4:
      return True
      
    # Keep batteries charged mode:
    # 9: 'Keep batteries charged' mode enabled
    if self._dbusData['BatteryLifeState'] == 9 and self._dbusData['Soc'] > 95 and self._dbusservice['pvinverter']['/State'] > 0:
      return True
    
    if self._dbusData['BatteryLifeState'] == 9 and self._dbusData['Soc'] == 100:
      return True
    
    # Optimized mode without BatteryLife:
    # 10: Self consumption, SoC at or above minimum SoC
    # 11: Self consumption, SoC is below minimum SoC
    # 12: Recharge, SOC dropped 5% or more below minimum SoC
    if self._dbusData['BatteryLifeState'] == 10:
      return True
      
    return False
  
  
  def _inverterOn(self):
    logging.info("Inverter On ")
    self._MQTTclient.publish(self._devcontrolPath + '/0/0', 1)
    self._dbusservice['vebus']['/State'] = 9
  
  
  def _inverterOff(self):
    logging.info("Inverter Off ")
    self._MQTTclient.publish(self._devcontrolPath + '/0/1', 1)
    self._dbusservice['vebus']['/State'] = 0
  

  def _inverterSetLimit(self, newLimit):
    self._inverterSetPower(newLimit, False)
    self._dbusservice['pvinverter']['/Ac/PowerLimit'] = newLimit
    

  def _inverterSetPower(self, power, force=False):
    newPower      = int(int(power                                             ) / 2) * 2  
    currentPower  = int(int(self._dbusservice['pvinverter']['/Ac/PowerLimit'] ) / 2) * 2
    
    if newPower < 25:
      newPower = 25
        
    if newPower != currentPower or force == True:
      self._MQTTclient.publish(self._devcontrolPath + '/0/11', newPower)
      self._powerLimitCounter = 0
  

  def _inverterLoop(self):
    # 0.5s interval 
    self._inverterLoopCounter +=1
    self._inverterUpdate()
    self._powerLimitCounter +=1

    self._gridPowerAvg.pop(0)
    self._gridPowerAvg.append(self._dbusData['GridPower'])

    # Alternate zero feed-in mode
    if (self.settings['/ZeroFeedInMode'] == 1 and self._dbusservice['pvinverter']['/State'] >= 2 and self._dbusData['PvPowerLimiterActive'] ==1):

      if self._powerLimitCounter >= self.settings['/ZeroFeedInInterval'] * 2:
        if (self._dbusData['GridPower'] < self.settings['/ZeroFeedInTarget'] - self.settings['/ZeroFeedInMin'] 
          or self._dbusData['GridPower'] > self.settings['/ZeroFeedInTarget'] + self.settings['/ZeroFeedInMax']):
            
            if self._dbusData['GridPower'] < self.settings['/ZeroFeedInTarget'] - 2 * self.settings['/ZeroFeedInMin']:
                gridPowerTarget = self._dbusData['GridPower']
            else:
                gridPowerTarget = sum(self._gridPowerAvg) / len(self._gridPowerAvg)

            loadPower = self._dbusservice['pvinverter']['/Ac/Power'] + gridPowerTarget 
            newTarget = min(loadPower - self.settings['/ZeroFeedInTarget'] , self._dbusservice['pvinverter']['/Ac/MaxPower'])
            newTarget = max(newTarget, 25)
            self._inverterSetLimit(newTarget)

    #5s interval
    if self._inverterLoopCounter % 10 == 0:
      self._pvPowerAvg.pop(0)
      self._pvPowerAvg.append(self._dbusData['DcPvPower'])

    # 10s interval
    if self._inverterLoopCounter % 20 == 0:
      self._checkInverterState()
    
    # 5min interval
    if self._inverterLoopCounter % 600 == 0:
      self._inverterLoopCounter = 0

      if self._dbusservice['pvinverter']['/State'] > 1:
        self._inverterSetPower(self._dbusservice['pvinverter']['/Ac/PowerLimit'], True)

    return True


  def _inverterUpdate(self):   
    try:
      
      pvinverter_phase = 'L' + str(self.settings['/Phase'])
      
      if self.settings['/Shelly/PowerMeter'] == 1 and self._shelly == True:
        shellyData = self._getShellyData()
        power = shellyData['meters'][0]['power']
      else:
        power = self._inverterData['ch0/P_AC']
      
      #send data to DBus
      for phase in ['L1', 'L2', 'L3']:
        pre = '/Ac/' + phase

        if phase == pvinverter_phase:
          self._dbusservice['pvinverter'][pre + '/Voltage'] = self._inverterData['ch0/U_AC']
          self._dbusservice['pvinverter'][pre + '/Current'] = self._inverterData['ch0/I_AC']
          self._dbusservice['pvinverter'][pre + '/Power'] = power
          self._dbusservice['pvinverter'][pre + '/Energy/Forward'] = self._inverterData['ch0/YieldTotal']
         
        else:
          self._dbusservice['pvinverter'][pre + '/Voltage'] = 0
          self._dbusservice['pvinverter'][pre + '/Current'] = 0
          self._dbusservice['pvinverter'][pre + '/Power'] = 0
          self._dbusservice['pvinverter'][pre + '/Energy/Forward'] = 0
         
      self._dbusservice['pvinverter']['/Ac/Power'] = power
      self._dbusservice['pvinverter']['/Ac/Energy/Forward'] = self._dbusservice['pvinverter']['/Ac/' + pvinverter_phase + '/Energy/Forward']
            
      dcCurrent = 0
      for i in range(1, 5):
        dcCurrent -= self._inverterData[f'ch{i}/I_DC']
      
      self._dbusservice['vebus']['/Dc/0/Current'] = dcCurrent   
      self._dbusservice['vebus']['/Dc/0/Voltage'] = self._inverterData['ch1/U_DC']
      
      self._dbusservice['pvinverter']['/Dc/Power'] = self._inverterData['ch0/P_DC']
      self._dbusservice['pvinverter']['/Dc/Current'] = 0 - dcCurrent
      self._dbusservice['pvinverter']['/Dc/Voltage'] = self._inverterData['ch1/U_DC']
      
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
    
    self._dbusData['Soc'] = self._dbus.get_object('com.victronenergy.system', '/Dc/Battery/Soc').GetValue()
    self._dbusData['BatteryLifeState'] = self._dbus.get_object('com.victronenergy.settings', '/Settings/CGwacs/BatteryLife/State').GetValue()
    self._dbusData['Hub'] = self._dbus.get_object('com.victronenergy.system', '/Hub').GetValue()
    self._dbusData['PvPowerLimiterActive'] = self._dbus.get_object('com.victronenergy.hub4', '/PvPowerLimiterActive').GetValue()
    
    logging.info("'/Ac/Power': %s  'Soc': %s  'BLS': %s  'PvAvg': %i" % (
      self._dbusservice['pvinverter']['/Ac/Power'], 
      self._dbusData['Soc'],
      self._dbusData['BatteryLifeState'],
      sum(self._pvPowerAvg) / len(self._pvPowerAvg)
      ))
    
    return True
    
  
  def _init_MQTT(self):
    self._MQTTclient = mqtt.Client(self._MQTTName) # create new instance
    self._MQTTclient.on_disconnect = self._on_MQTT_disconnect
    self._MQTTclient.on_connect = self._on_MQTT_connect
    self._MQTTclient.on_message = self._on_MQTT_message
    self._MQTTclient.connect(self._brokerAddress)  # connect to broker
    self._MQTTclient.loop_start()

  
  def _on_MQTT_disconnect(self, client, userdata, rc):
    print("Client Got Disconnected")
    if rc != 0:
        print('Unexpected MQTT disconnection. Will auto-reconnect')

    else:
        print('rc value:' + str(rc))

    try:
        print("Trying to Reconnect")
        client.connect(self._brokerAddress)
        self._MQTTconnected = 1
    except Exception as e:
        logging.exception("Fehler beim reconnecten mit Broker")
        print("Error in Retrying to Connect with Broker")
        self._MQTTconnected = 0
        print(e)


  def _on_MQTT_connect(self, client, userdata, flags, rc):
    if rc == 0:
        self._MQTTconnected = 1
        
        for k,v in self._inverterData.items():
          client.subscribe(f'{self._inverterPath}/{k}')
          
    else:
        print("Failed to connect, return code %d\n", rc)


  def _on_MQTT_message(self, client, userdata, msg):
      try:
          for k,v in self._inverterData.items():
            if msg.topic == f'{self._inverterPath}/{k}':
              self._inverterData[k] = float(msg.payload)
              return
             
      except Exception as e:
          logging.critical('Error at %s', '_update', exc_info=e)


  def _getShellyStatusUrl(self):
    
    URL = "http://%s:%s@%s/status" % (self.settings['/Shelly/User'], self.settings['/Shelly/Pwd'], self.settings['/Shelly/Url'])
    URL = URL.replace(":@", "")
   
    return URL
    
 
  def _getShellyData(self):
    URL = self._getShellyStatusUrl()
    meter_r = requests.get(url = URL)
    
    # check for response
    if not meter_r:
        raise ConnectionError("No response from Shelly 1PM - %s" % (URL))
    
    meter_data = meter_r.json()     
    
    # check for Json
    if not meter_data:
        raise ValueError("Converting response to JSON failed")
    
    return meter_data
  
  def _checkShelly(self):
    try:
      shellyData = self._getShellyData()
      shellyPower = shellyData['meters'][0]['power']
      logging.info("Shelly OK ")
      
      if self.settings['/Shelly/Enable'] == 1:
        self._shelly = True
      else:
        self._shelly = False
      
      return
      
    except Exception as e:
      self._shelly = False
      logging.info("Shelly Fail")
      return
  
  
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
      logging.info("Start");
  
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
