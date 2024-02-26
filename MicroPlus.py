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
import configparser # for config/ini file
import dbus

from threading import Thread

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

EXTINFO = 15

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


################################################################################
#                                                                              #
#   D-Bus Inverter Devices                                                     #
#                                                                              #
################################################################################

class DbusInverter:
  def __init__(self,service,dbusmonitor):
    self._service = service
    self._dbusmonitor = dbusmonitor
    self._energyOffset = None

  def _getMaxPower(self):
    if self._dbusmonitor.get_value(self._service,'/Enabled') == 1:
      return self._dbusmonitor.get_value(self._service,'/Ac/MaxPower') or 0
    return 0
  
  def _getMinPower(self):
    if self._dbusmonitor.get_value(self._service,'/Enabled') == 1:
      return self._dbusmonitor.get_value(self._service,'/Ac/MinPower') or 0
    return 0

  def _getPowerLimit(self):
    if self._dbusmonitor.get_value(self._service,'/Enabled') == 1:
      return self._dbusmonitor.get_value(self._service,'/Ac/PowerLimit') or 0
    return 0

  def _setPowerLimit(self,newLimit):
    self._dbusmonitor.set_value(self._service,'/Ac/PowerLimit',newLimit)
  
  def _getActive(self):
    if self._dbusmonitor.get_value(self._service,'/DisableFeedIn') == 0:
      return True
    return False

  def _setActive(self,active):
    if active == True:
      self._dbusmonitor.set_value(self._service,'/DisableFeedIn',0) 
    else:
      self._dbusmonitor.set_value(self._service,'/DisableFeedIn',1)

  def _getEnabled(self):
    if self._dbusmonitor.get_value('/DisableFeedIn') == 0:
      return True
    return False

  def _getEnergy(self):
    energy = self._dbusmonitor.get_value(self._service,'/Ac/Energy/Forward') or 0
    if self._energyOffset == None:
      if energy > 0:
        self._energyOffset = energy
      return 0
    else:
      return energy - self._energyOffset

  MaxPower = property(fget=_getMaxPower)
  MinPower = property(fget=_getMinPower)
  PowerLimit = property(fget=_getPowerLimit, fset=_setPowerLimit)
  Active = property(fget=_getActive, fset=_setActive)
  Enabled = property(fget=_getEnabled)
  Energy = property(fget=_getEnergy)
  DcVoltage = property(fget=lambda self: self._dbusmonitor.get_value(self._service,'/Dc/Voltage') or 0)
  DcCurrent = property(fget=lambda self: self._dbusmonitor.get_value(self._service,'/Dc/Current') or 0)
  DcPower = property(fget=lambda self: self._dbusmonitor.get_value(self._service,'/Dc/Power') or 0)
  Efficiency = property(fget=lambda self: self._dbusmonitor.get_value(self._service,'/Ac/Efficiency') or 0)
  AcPower = property(fget=lambda self: self._dbusmonitor.get_value(self._service,'/Ac/Power') or 0)
  Temperature = property(fget=lambda self: self._dbusmonitor.get_value(self._service,'/Temperature') or 0)

  def AcPowerL(self,phase):
    return self._dbusmonitor.get_value(f'/Ac/L{phase}/Power') or 0
  
  def AcCurrentL(self,phase):
    return self._dbusmonitor.get_value(f'/Ac/L{phase}/Current') or 0
  
  def AcVoltageL(self,phase):
    return self._dbusmonitor.get_value(f'/Ac/L{phase}/Voltage') or 0

  def setPowerLimit(self,newLimit):
    newLimit = int(min(newLimit, self.MaxPower))
    newLimit = int(max(newLimit, self.MinPower))
    self.PowerLimit = newLimit
    return newLimit


################################################################################
#                                                                              #
#   Inverter Control                                                           #
#                                                                              #
################################################################################

class MicroPlus:
  def __init__(self):
    self.settings = None
    self._controlLoopCounter = 0
    self._pvPowerHistory =  [0] * 60
    self._pvPowerAvg =  [0] * 20
    self._gridPower = 0
    self._gridPowerAvg =  [0] * 6
    self._loadPower = 0
    self._loadPowerHistory =  [600] * 30
    self._loadPowerMin = [600]*40
    self._powerLimitCounter = 10
    self._dbus = dbusconnection()
    self._powerMeterService = None
    self._excessPower = 0
    self._trottlingPower = 0
    self._excessCounter = 0
    self._devinst = 50
    self._dbusservice = None
    self._inverterDcShutdown = False

    self._devices = []
    self._initDbusMonitor()
    self._initDeviceSettings()

    self._refreshAcloads()

    self._checkState()

    # add _controlLoop function 'timer'
    gobject.timeout_add(500, self._controlLoop)


  def _initDbusservice(self):
    paths = {
      '/AvailableAcLoads':                  {'initial': '', 'textformat': None},
      '/StartLimit':                        {'initial': 0, 'textformat': None},
      '/PvAvgPower':                        {'initial': 0, 'textformat': _w},
      '/Info':                              {'initial': '', 'textformat': None},
      #'/Debug0':                            {'initial': 0, 'textformat': None},
      #'/Debug1':                           {'initial': 0, 'textformat': None},
      #'/Debug2':                           {'initial': 25, 'textformat': None},
      #'/Debug3':                           {'initial': 30, 'textformat': None},

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
      '/Ac/Inverter/L1/P':                  {'initial': 0, 'textformat': _w},
      '/Ac/Inverter/L2/P':                  {'initial': 0, 'textformat': _w},
      '/Ac/Inverter/L3/P':                  {'initial': 0, 'textformat': _w},
      '/Ac/Inverter/L1/I':                  {'initial': 0, 'textformat': _a},
      '/Ac/Inverter/L2/I':                  {'initial': 0, 'textformat': _a},
      '/Ac/Inverter/L3/I':                  {'initial': 0, 'textformat': _a},
      '/Ac/ActiveIn/P':                     {'initial': 0, 'textformat': _w},
      '/Ac/ActiveIn/Connected':             {'initial': 0, 'textformat': None},
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
      '/Ac/ActiveIn/ActiveInput':           {'initial': 0, 'textformat': None},
      '/Ac/In/1/CurrentLimit':              {'initial': 0, 'textformat': None},
      '/Ac/In/1/CurrentLimitIsAdjustable':  {'initial': 0, 'textformat': None},
      '/Ac/In/2/CurrentLimit':              {'initial': 0, 'textformat': None},
      '/Ac/In/2/CurrentLimitIsAdjustable':  {'initial': 0, 'textformat': None},
      '/Settings/SystemSetup/AcInput1':     {'initial': 1, 'textformat': None},
      '/Settings/SystemSetup/AcInput2':     {'initial': 0, 'textformat': None},
      '/Ac/PowerMeasurementType':           {'initial': 4, 'textformat': None},
      '/Ac/State/IgnoreAcIn1':              {'initial': 0, 'textformat': None},
      '/Ac/State/IgnoreAcIn2':              {'initial': 0, 'textformat': None},

      '/Ac/Power':                          {'initial': 0, 'textformat': _w},
      '/Ac/Efficiency':                     {'initial': 0, 'textformat': _pct},
      '/Ac/PowerLimit':                     {'initial': 0, 'textformat': _w},
      '/Ac/MaxPower':                       {'initial': 0, 'textformat': _w},
      '/Ac/Energy/Forward':                 {'initial': None,     'textformat': _kwh},

      '/Ac/NumberOfPhases':                 {'initial': 3, 'textformat': None},
      '/Ac/NumberOfAcInputs':               {'initial': 1, 'textformat': None},

      '/Alarms/HighDcCurrent':              {'initial': 0, 'textformat': None},
      '/Alarms/HighDcVoltage':              {'initial': 0, 'textformat': None},
      '/Alarms/LowBattery':                 {'initial': 0, 'textformat': None},
      '/Alarms/PhaseRotation':              {'initial': 0, 'textformat': None},
      '/Alarms/Ripple':                     {'initial': 0, 'textformat': None},
      '/Alarms/TemperatureSensor':          {'initial': 0, 'textformat': None},
      '/Alarms/L1/HighTemperature':         {'initial': 0, 'textformat': None},
      '/Alarms/L1/LowBattery':              {'initial': 0, 'textformat': None},
      '/Alarms/L1/Overload':                {'initial': 0, 'textformat': None},
      '/Alarms/L1/Ripple':                  {'initial': 0, 'textformat': None},
      '/Alarms/L2/HighTemperature':         {'initial': 0, 'textformat': None},
      '/Alarms/L2/LowBattery':              {'initial': 0, 'textformat': None},
      '/Alarms/L2/Overload':                {'initial': 0, 'textformat': None},
      '/Alarms/L2/Ripple':                  {'initial': 0, 'textformat': None},
      '/Alarms/L3/HighTemperature':         {'initial': 0, 'textformat': None},
      '/Alarms/L3/LowBattery':              {'initial': 0, 'textformat': None},
      '/Alarms/L3/Overload':                {'initial': 0, 'textformat': None},
      '/Alarms/L3/Ripple':                  {'initial': 0, 'textformat': None},

      '/Dc/0/Power':                        {'initial': 0, 'textformat': _w},
      '/Dc/0/Current':                      {'initial': 0, 'textformat': _a},
      '/Dc/0/Voltage':                      {'initial': 0, 'textformat': _v},
      '/Dc/0/Temperature':                  {'initial': 0, 'textformat': None},

      '/Mode':                              {'initial': 3, 'textformat': None},
      '/ModeIsAdjustable':                  {'initial': 1, 'textformat': None},

      '/VebusChargeState':                  {'initial': 0, 'textformat': None},
      '/VebusSetChargeState':               {'initial': 0, 'textformat': None},

      '/Leds/Inverter':                     {'initial': 1, 'textformat': None},

      '/Bms/AllowToCharge':                 {'initial': 0, 'textformat': None},
      '/Bms/AllowToDischarge':              {'initial': 0, 'textformat': None},
      '/Bms/BmsExpected':                   {'initial': 0, 'textformat': None},
      '/Bms/Error':                         {'initial': 0, 'textformat': None},

      '/Soc':                               {'initial': 0, 'textformat': None},
      '/State':                             {'initial': 0, 'textformat': None},
      '/VebusError':                        {'initial': 0, 'textformat': None},
      '/Temperature':                       {'initial': 0, 'textformat': _c},

      '/Hub4/L1/AcPowerSetpoint':           {'initial': 0, 'textformat': None},
      '/Hub4/DisableCharge':                {'initial': 0, 'textformat': None},
      '/Hub4/DisableFeedIn':                {'initial': 1, 'textformat': None},
      '/Hub4/L2/AcPowerSetpoint':           {'initial': 0, 'textformat': None},
      '/Hub4/L3/AcPowerSetpoint':           {'initial': 0, 'textformat': None},
      '/Hub4/DoNotFeedInOvervoltage':       {'initial': 0, 'textformat': None},
      '/Hub4/L1/MaxFeedInPower':            {'initial': 0, 'textformat': None},
      '/Hub4/L2/MaxFeedInPower':            {'initial': 0, 'textformat': None},
      '/Hub4/L3/MaxFeedInPower':            {'initial': 0, 'textformat': None},
      '/Hub4/TargetPowerIsMaxFeedIn':       {'initial': 0, 'textformat': None},
      '/Hub4/FixSolarOffsetTo100mV':        {'initial': 0, 'textformat': None},
      '/Hub4/AssistantId':                  {'initial': 5, 'textformat': None},

      '/PvInverter/Disable':                {'initial': 0, 'textformat': None},
      '/SystemReset':                       {'initial': 0, 'textformat': None},
      '/Enabled':                           {'initial': 1, 'textformat': None},

      '/Energy/AcIn1ToAcOut':               {'initial': 0, 'textformat': _kwh},
      '/Energy/AcIn1ToInverter':            {'initial': 0, 'textformat': _kwh},
      '/Energy/AcIn2ToAcOut':               {'initial': 0, 'textformat': _kwh},
      '/Energy/AcIn2ToInverter':            {'initial': 0, 'textformat': _kwh},
      '/Energy/AcOutToAcIn1':               {'initial': 0, 'textformat': _kwh},
      '/Energy/AcOutToAcIn2':               {'initial': 0, 'textformat': _kwh},
      '/Energy/InverterToAcIn1':            {'initial': 0, 'textformat': _kwh},
      '/Energy/InverterToAcIn2':            {'initial': 0, 'textformat': _kwh},
      '/Energy/InverterToAcOut':            {'initial': 0, 'textformat': _kwh},
      '/Energy/OutToInverter':              {'initial': 0, 'textformat': _kwh},

    }

    # add path values to dbus
    for path, settings in paths.items():
      self._dbusservice.add_path(
        path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handleChangedValue)

    self._dbusservice['/ProductId'] = 0xFFF1
    self._dbusservice['/FirmwareVersion'] = 0x482
    self._dbusservice['/ProductName'] = 'MicroPlus'
    self._dbusservice['/Connected'] = 1
    self._dbusservice['/Ac/MaxPower'] = self._availablePower()


  def _handleChangedValue(self, path, value):
    #logging.log(EXTINFO,"dbus_value_changed: %s %s" % (path, value,))

    if path == '/Hub4/L1/AcPowerSetpoint' and self._powerLimitCounter >= self.settings['/InverterMinimumInterval'] * 2 and self.settings['/LimitMode'] == 3:
      logging.log(EXTINFO,"AcPowerSetpoint: %s" % (value * 3))
      self._dbusservice['/Ac/PowerLimit'] = self._setLimit(-value * 3, self._dbusservice['/Hub4/L1/MaxFeedInPower'] * 3)

    if path == '/Hub4/L1/MaxFeedInPower' and self._powerLimitCounter >= self.settings['/InverterMinimumInterval'] * 3 and self.settings['/LimitMode'] == 3:
      logging.log(EXTINFO,"MaxFeedInPower: %s" % (value * 3))
      self._dbusservice['/Ac/PowerLimit'] = self._setLimit(-self._dbusservice['/Hub4/L1/AcPowerSetpoint'] * 3, value * 3)
    
    if path == '/Hub4/DisableFeedIn':
      logging.log(EXTINFO,"dbus_value_changed: %s %s" % (path, value,))
      self._dbusservice['/Hub4/DisableFeedIn'] = value
      self._checkState()
    
    if path == '/Mode':
      logging.log(EXTINFO,"dbus_value_changed: %s %s" % (path, value,))
      self._dbusservice['/Mode'] = value
      self._checkState()

    if path == '/Ac/PowerLimit':
      logging.log(EXTINFO,"dbus_value_changed: %s %s" % (path, value,))
      if self.settings['/LimitMode'] == 4:
        limit = self._setLimit(value, self._maxFeedInPower())
        if limit == value:
          return True
        else:
          self._dbusservice['/Ac/PowerLimit'] = limit
          return False
      else:
        return False

    return True


  def _controlLoop(self):
    if self._dbusservice == None:
        return True
    
    try:
      # 0.5s interval
      self._controlLoopCounter +=1
      self._powerLimitCounter +=1
      
      self._updateVebusTotal()
      self._getSystemPower()
      self._calcLimit()

      # 5s interval
      if self._controlLoopCounter % 10 == 0:
        self._infoTopic()
        self._calcFeedInExcess()

      # 5min interval
      if self._controlLoopCounter % 600 == 0:
        self._controlLoopCounter = 0
        self._checkState()
      
      if self._excessPower > 0 and self.settings['/LimitMode'] == 3 and self._powerLimitCounter >= self.settings['/GridTargetInterval'] * 4:
        self._dbusservice['/Ac/PowerLimit'] = self._setLimit(-self._dbusservice['/Hub4/L1/AcPowerSetpoint'] * 3, self._dbusservice['/Hub4/L1/MaxFeedInPower'] * 3)

      if self._inverterDcShutdown == True:
        if self._dbusservice['/Dc/0/Voltage'] >= self.settings['/InverterDcRestartVoltage']:
          self._inverterDcShutdown = False
          self._checkState()
      else:
        if self._dbusservice['/Dc/0/Voltage'] <= self.settings['/InverterDcShutdownVoltage']:
          self._inverterDcShutdown = True
          self._checkState()

    except Exception as e:
      logging.exception('Error at %s', '_inverterLoop', exc_info=e)

    return True


  def _initDbusMonitor(self):
    dummy = {'code': None, 'whenToLog': 'configChange', 'accessLevel': None}
    dbus_tree = {
      'com.victronenergy.settings': { # Not our settings
        '/Settings/CGwacs/BatteryLife/State': dummy,
        '/Settings/CGwacs/OvervoltageFeedIn': dummy,
        '/Settings/CGwacs/MaxFeedInPower': dummy,
        '/Settings/CGwacs/AcPowerSetPoint' : dummy,
        '/Settings/CGwacs/Hub4Mode' : dummy,
        '/Settings/System/TimeZone' : dummy,
      },
      'com.victronenergy.system': {
        '/Dc/Battery/Soc': dummy,
        '/Dc/Battery/Power': dummy,
        '/Dc/Pv/Power': dummy,
        '/Ac/Consumption/L1/Power': dummy,
        '/Ac/Consumption/L2/Power': dummy,
        '/Ac/Consumption/L3/Power': dummy,
        '/Ac/Grid/L1/Power': dummy,
        '/Ac/Grid/L2/Power': dummy,
        '/Ac/Grid/L3/Power': dummy,
        '/VebusService': dummy,
      },
      'com.victronenergy.hub4': {
        '/PvPowerLimiterActive': dummy,
        '/MaxDischargePower': dummy,
      },
      'com.victronenergy.acload': {
        '/Ac/Power': dummy,
        '/Ac/PowerLimit': dummy,
        '/Ac/MaxPower': dummy,
        '/Ac/MinPower': dummy,
        '/Ac/Efficiency': dummy,
        '/Ac/Energy/Forward': dummy,
        '/Ac/L1/Power': dummy,
        '/Ac/L2/Power': dummy,
        '/Ac/L3/Power': dummy,
        '/Ac/L1/Current': dummy,
        '/Ac/L2/Current': dummy,
        '/Ac/L3/Current': dummy,
        '/Ac/L1/Voltage': dummy,
        '/Ac/L2/Voltage': dummy,
        '/Ac/L3/Voltage': dummy,
        '/Dc/Power': dummy,
        '/Dc/Current': dummy,
        '/Dc/Voltage': dummy,
        '/Temperature': dummy,
        '/CustomName': dummy,
        '/ProductName': dummy,
        '/DeviceInstance': dummy,
        '/Connected': dummy,
        '/Enabled': dummy,
        '/DisableFeedIn': dummy,
      },
      'com.victronenergy.solarcharger': {
        '/MppOperationMode': dummy,
      },
    }
    self._dbusmonitor = DbusMonitor(dbus_tree, valueChangedCallback=self._dbusValueChanged, deviceAddedCallback= self._dbusDeviceAdded, deviceRemovedCallback=self._dbusDeviceRemoved)


  def _dbusValueChanged(self,dbusServiceName, dbusPath, options, changes, deviceInstance):
    if dbusPath in {'/Dc/Battery/Soc','/Settings/CGwacs/BatteryLife/State','/Hub','/PvPowerLimiterActive'}:
      logging.log(EXTINFO,"dbus_value_changed: %s %s %s" % (dbusServiceName, dbusPath, changes['Value']))

    if dbusPath in {'/Settings/CGwacs/BatteryLife/State','/Dc/Battery/Soc'}:
      self._checkState()

    elif dbusPath == '/Connected':
      self._refreshAcloads()

    elif dbusPath == '/Settings/CGwacs/OvervoltageFeedIn':
      if changes['Value'] == 0:
        self._excessPower = 0

    elif self._dbusservice== None:
      return
    
    elif dbusPath == '/Enabled':
      self._dbusservice['/Ac/MaxPower'] = self._availablePower()
      self._devices.sort(reverse=True, key=lambda x: x.MaxPower)
      self._checkState()

    elif dbusPath == '/Ac/MaxPower':
      self._dbusservice['/Ac/MaxPower'] = self._availablePower()

    #elif dbusPath == '/VebusService':
    #  self._devices.sort(reverse=True, key=lambda x: x.IsMaster)

    elif dbusPath == '/MaxDischargePower':
      if (self._actualLimit() > changes['Value']) and (self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/Hub4Mode') != 3):
        self._dbusservice['/Ac/PowerLimit'] = self._setLimit(changes['Value'], self._maxFeedInPower())

    return


  def _dbusDeviceAdded(self,dbusservicename, instance):
    logging.info("dbus device added: %s %s " % (dbusservicename, instance))
    self._refreshAcloads()
    return


  def _dbusDeviceRemoved(self,dbusservicename, instance):
    logging.info("dbus device removed: %s %s " % (dbusservicename, instance))
    self._refreshAcloads()
    return


  def _initDeviceSettings(self):
    if self.settings:
        return

    path = '/Settings/Devices/mPlus_0'
    def_inst = '%s:%s' % ('vebus', self._devinst)

    SETTINGS = {
        '/ClassAndVrmInstance':           [path + '/ClassAndVrmInstance', def_inst, 0, 0],
        '/StartLimit':                    [path + '/StartLimit', 0, 0, 1],
        '/StartLimitMin':                 [path + '/StartLimitMin', 50, 50, 500],
        '/StartLimitMax':                 [path + '/StartLimitMax', 500, 100, 2000],
        '/LimitMode':                     [path + '/LimitMode', 3, 0, 4],
        '/PowerMeterInstance':            [path + '/PowerMeterInstance', 0, 0, 0],
        '/GridTargetDevMin':              [path + '/GridTargetDevMin', 25, 5, 100],
        '/GridTargetDevMax':              [path + '/GridTargetDevMax', 25, 5, 100],
        '/GridTargetInterval':            [path + '/GridTargetInterval', 15, 3, 60],
        '/BaseLoadPeriod':                [path + '/BaseLoadPeriod', 0.5, 0.5, 10],
        '/InverterMinimumInterval':       [path + '/InverterMinimumInterval', 5.0, 2, 15],
        '/InverterDcShutdownVoltage':     [path + '/InverterDcShutdownVoltage', 46.0, 16.0, 59.9],
        '/InverterDcRestartVoltage':      [path + '/InverterDcRestartVoltage', 46.5, 16.1, 60],
        '/Settings/SystemSetup/AcInput1': ['/Settings/SystemSetup/AcInput1', 1, 0, 1],
        '/Settings/SystemSetup/AcInput2': ['/Settings/SystemSetup/AcInput2', 0, 0, 1],
    }

    self.settings = SettingsDevice(self._dbus, SETTINGS, self._settingChanged)
    role, self._devinst = self.get_role_instance()


  def _settingChanged(self, setting, oldvalue, newvalue):
    logging.info("setting changed, setting: %s, old: %s, new: %s" % (setting, oldvalue, newvalue))

    if setting == '/PowerMeterInstance':
      self._refreshAcloads()

    elif setting == '/StartLimit' or setting == '/StartLimitMax':
      self._checkStartLimit()

    elif setting == '/InverterDcRestartVoltage':
      if self.settings['/InverterDcShutdownVoltage'] >= newvalue:
        self.settings['/InverterDcShutdownVoltage'] = newvalue - 0.1

    elif setting == '/InverterDcShutdownVoltage':
      if self.settings['/InverterDcRestartVoltage'] <= newvalue:
        self.settings['/InverterDcRestartVoltage'] = newvalue + 0.1


  def get_role_instance(self):
    val = self.settings['/ClassAndVrmInstance'].split(':')
    return val[0], int(val[1])


  def _updateVebusTotal(self):
    inverterTotalPower = [0] * 3
    inverterTotalCurrent = [0] * 3
    inverterAcVoltage = [0] * 3
    inverterTotalPowerDC = 0
    inverterTotalCurrentDC = 0
    inverterTotalEnergy = 0
    voltageDC = 0
    efficiency = 0
    efficiencyP = 0
    temperature = 0

    if len(self._devices) == 0:
      voltageDC = 0
    else:
      voltageDC = self._devices[0].DcVoltage

    if self._powerMeterService != None:
      self._dbusservice['/Ac/Power'] =  self._dbusmonitor.get_value(self._powerMeterService,'/Ac/Power') or 0
      for i in range(0,3):
        inverterTotalPower[i] = self._dbusmonitor.get_value(self._powerMeterService,f'/Ac/L{i+1}/Power') or 0
        inverterTotalCurrent[i] = self._dbusmonitor.get_value(self._powerMeterService,f'/Ac/L{i+1}/Current') or 0
        inverterAcVoltage[i] = max(inverterAcVoltage[i],self._dbusmonitor.get_value(self._powerMeterService,f'/Ac/L{i+1}/Voltage') or 0)
      inverterTotalPowerDC = self._dbusservice['/Ac/Power'] / self._efficiency()

      if voltageDC > 0:
        inverterTotalCurrentDC = (inverterTotalPowerDC / voltageDC) * -1
      else:
        inverterTotalCurrentDC = 0

      for device in self._devices:
        inverterTotalEnergy += device.Energy

    else:
      for device in self._devices:
        inverterTotalPowerDC += device.DcPower
        inverterTotalCurrentDC += device.DcCurrent
        inverterTotalEnergy += device.Energy
        for i in range(0,3):
          pre = f'/Ac/L{i+1}'
          inverterTotalPower[i] += device.AcPowerL(i+1)
          inverterTotalCurrent[i] += device.AcCurrentL(i+1)
          inverterAcVoltage[i] = max(inverterAcVoltage[i],device.AcVoltageL(i+1))
      self._dbusservice['/Ac/Power'] = sum(inverterTotalPower)

    for device in self._devices:
      eff = device.Efficiency
      effP = device.AcPower
      if eff > 0:
        efficiency += effP / eff
      efficiencyP += effP
      temperature = max(temperature, device.Temperature)

    for i in range(0,3):
      self._dbusservice[f'/Ac/ActiveIn/L{i+1}/P'] = 0 - inverterTotalPower[i]
      self._dbusservice[f'/Ac/ActiveIn/L{i+1}/I'] = 0 - inverterTotalCurrent[i]
      self._dbusservice[f'/Ac/ActiveIn/L{i+1}/V'] = inverterAcVoltage[i]
    self._dbusservice['/Ac/ActiveIn/P'] = 0 - self._dbusservice['/Ac/Power']
    self._dbusservice['/Dc/0/Power'] = inverterTotalPowerDC
    self._dbusservice['/Dc/0/Current'] = inverterTotalCurrentDC
    self._dbusservice['/Dc/0/Voltage'] = voltageDC
    self._dbusservice['/Energy/InverterToAcIn1'] = inverterTotalEnergy
    self._dbusservice['/Temperature'] = temperature
    if efficiency == 0:
      self._dbusservice['/Ac/Efficiency'] = 0
    else:
      self._dbusservice['/Ac/Efficiency'] = efficiencyP / efficiency


  def _getSystemPower(self):

    self._gridPower = (self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Grid/L1/Power') or 0) + \
                      (self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Grid/L2/Power') or 0)+ \
                      (self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Grid/L3/Power') or 0)
    self._loadPower = (self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Consumption/L1/Power') or 0) + \
                      (self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Consumption/L2/Power') or 0) + \
                      (self._dbusmonitor.get_value('com.victronenergy.system','/Ac/Consumption/L3/Power') or 0)

    self._gridPowerAvg.pop(0)
    self._gridPowerAvg.append(self._gridPower)

    self._loadPowerHistory.pop(len(self._loadPowerHistory)-1)
    self._loadPowerHistory.insert(0,self._loadPower)

    #1s interval
    if self._controlLoopCounter % 2 == 0:
      self._pvPowerHistory.pop(len(self._pvPowerHistory)-1)
      self._pvPowerHistory.insert(0,self._dbusmonitor.get_value('com.victronenergy.system','/Dc/Pv/Power') or 0)

    # 15s interval
    if self._controlLoopCounter % 30 == 0:
      self._loadPowerMin.pop(len(self._loadPowerMin)-1)
      self._loadPowerMin.insert(0,min(self._loadPowerHistory))

    # 60s interval
    if self._controlLoopCounter % 120 == 0:
      self._pvPowerAvg.pop(len(self._pvPowerAvg)-1)
      self._pvPowerAvg.insert(0,int(sum(self._pvPowerHistory) / len(self._pvPowerHistory)))
      self._dbusservice['/PvAvgPower'] = int(sum(self._pvPowerAvg) / len(self._pvPowerAvg))


  def _calcLimit(self):
    
    if self._dbusservice['/State'] != 0:
      
      newTarget = 0

      # 1min interval
      if self._controlLoopCounter % 120 == 0:
        self._checkStartLimit()

      # Maximum power
      if self.settings['/LimitMode'] == 0:
        # 30s interval
        if self._controlLoopCounter % 60 == 0:
          newTarget = 0 
          for device in self._devices:
            newTarget += device.MaxPower
          self._dbusservice['/Ac/PowerLimit'] = self._setLimit(newTarget, self._maxFeedInPower())


      # Grid target limit mode
      if self.settings['/LimitMode'] == 1 and self._powerLimitCounter >= self.settings['/GridTargetInterval'] * 2:
        gridSetpoint = self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/AcPowerSetPoint')

        if self._gridPower < gridSetpoint - self.settings['/GridTargetDevMin'] \
        or self._gridPower > gridSetpoint + self.settings['/GridTargetDevMax'] \
        or self._excessPower > 0:

          if self._gridPower < gridSetpoint - 2 * self.settings['/GridTargetDevMin']:
            gridPowerTarget = self._gridPower
          else:
            gridPowerTarget = sum(self._gridPowerAvg) / len(self._gridPowerAvg)

          newTarget = self._dbusservice['/Ac/Power'] + gridPowerTarget - gridSetpoint
          self._dbusservice['/Ac/PowerLimit'] = self._setLimit(newTarget, self._maxFeedInPower())

      # Base load limit mode
      if self.settings['/LimitMode'] == 2:
        if (self._gridPower < 0 or self._excessPower > self._actualLimit()) and self._powerLimitCounter >= self.settings['/InverterMinimumInterval'] * 2:
          newTarget = self._actualLimit() + self._gridPower - 10
          logging.log(EXTINFO,"set limit1: %s" % (newTarget))
          self._dbusservice['/Ac/PowerLimit'] = self._setLimit(newTarget, self._maxFeedInPower())

        # 15s interval
        if self._controlLoopCounter % 30 == 0:
          newTarget = min(self._loadPowerMin[0:int(self.settings['/BaseLoadPeriod'] * 4)]) - 10
          if newTarget > self._actualLimit():
            logging.log(EXTINFO,"set limit2: %s" % (newTarget))
            self._dbusservice['/Ac/PowerLimit'] = self._setLimit(newTarget, self._maxFeedInPower())


  def _calcFeedInExcess(self):
    # Feed in excess
      if (self._dbusmonitor.get_value('com.victronenergy.system','/Dc/Battery/Soc') or 0) < 85:
        self._excessPower = 0
        self._trottlingPower = 0
        #self._dbusservice['/Debug0'] = self._trottlingPower
        #self._dbusservice['/Debug1'] = self._excessPower
        return

      deltaPmax = 25
      deltaPmin = 4
      deltaExp = 3
      stepsMax = 30

      pvPowerAvg = sum(self._pvPowerHistory[0:5]) / 5
      excessMax = (pvPowerAvg - max(self._dbusmonitor.get_value('com.victronenergy.system','/Dc/Battery/Power') or 0, 0)) * 1.1 * self._efficiency()

      if self._MpptIsThrottling() == True:
        if self._excessCounter < 0:
          self._excessCounter = 0
        else:
          self._excessCounter = min(self._excessCounter+1,stepsMax)

        if self._trottlingPower == 0:
          self._trottlingPower = self._dbusservice['/Ac/Power'] 
          self._trottlingPower = min(self._trottlingPower, self._availablePower(), excessMax)
          self._trottlingPower = max(self._trottlingPower, 50)
          self._excessCounter  = 0
          self._checkState()
        else:
          if self._trottlingPower < excessMax:
            excessDelta = deltaPmin + int(self._excessCounter**deltaExp * ((deltaPmax-deltaPmin) / (stepsMax**deltaExp + deltaPmin)))
            self._trottlingPower = min(self._trottlingPower + excessDelta, self._availablePower(), excessMax)
          
      else:
        if self._excessCounter > 0:
          self._excessCounter = 0
        else:
          self._excessCounter = max(self._excessCounter-1,-stepsMax)

        if self._trottlingPower > 0:
          if self._trottlingPower > excessMax:
            self._trottlingPower = excessMax
          elif self._trottlingPower > self._dbusservice['/Ac/Power'] * 0.9 or (self._dbusmonitor.get_value('com.victronenergy.system','/Dc/Battery/Soc') or 0) < 100:
            excessDelta = deltaPmin + int(abs(self._excessCounter)**deltaExp * ((deltaPmax-deltaPmin) / (stepsMax**deltaExp + deltaPmin)))
            self._trottlingPower = max(self._trottlingPower - excessDelta, 0)
          else:
            self._excessCounter = min(self._excessCounter+1,0)
          if self._trottlingPower ==0:
            self._checkState()

      if self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/OvervoltageFeedIn') == 1:
        self._excessPower = self._trottlingPower * self._efficiency()
        if self._excessPower < 50:
              self._excessPower = 0
      else:
        self._excessPower = 0

      #self._dbusservice['/Debug0'] = self._trottlingPower
      #self._dbusservice['/Debug1'] = self._excessPower
      #self._dbusservice['/Debug2'] = excessMax


  def _checkState(self):
    if self._dbusservice== None:
        return

    disableFeedIn = self._disableFeedIn()
    
    if disableFeedIn == False and self._dbusservice['/State'] == 0:
      if self.settings['/StartLimit'] == 1 and self._dbusservice['/PvAvgPower'] > 10:
        self._dbusservice['/StartLimit'] = self.settings['/StartLimitMin']
        self._checkStartLimit()
      else:
        for device in self._devices:
          device.PowerLimit = 1
          device.Active = True
      self._dbusservice['/State'] = 9
      if self.settings['/LimitMode'] == 4:
          self._setLimit(self._dbusservice['/Ac/PowerLimit'], self._maxFeedInPower())

    elif disableFeedIn == True and self._dbusservice['/State'] != 0:
      for device in self._devices:
        device.Active = False
      self._dbusservice['/StartLimit'] = 0
      self._dbusservice['/State'] = 0

    elif disableFeedIn == True:
      for device in self._devices:
        device.Active = False


  def _checkStartLimit(self):    
    if self._dbusservice['/StartLimit'] == 0:
      return False
    
    newLimit = max(self.settings['/StartLimitMin'], int(self._dbusservice['/PvAvgPower'] * 0.95))
    
    # Check end of StartLimit mode
    if newLimit >= self.settings['/StartLimitMax'] or self.settings['/StartLimit'] == 0 \
      or self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/BatteryLife/State') == 9:
        # Activate all inverter
        for device in self._devices:
          if device.Active == False:
            device.PowerLimit = 1
            device.Active = True
        self._dbusservice['/StartLimit'] = 0
        logging.log(EXTINFO,"Start limit off.")
        return False

    # Check available inverter power 
    if self._activePower() < newLimit:
      for device in self._devices:
        if device.Active == False:
          # Activate next inverter
          device.PowerLimit = 1
          device.Active = True 
          if self._activePower() >= newLimit:
            break
    else:
      for device in self._devices[::-1]:
        if device.Active == True:
          if self._activePower() - device.MaxPower > newLimit:
            # Deactivate last inverter
            device.Active = False
          else:
            break 

    self._dbusservice['/StartLimit'] = newLimit

    return True


  def _setLimit(self, newLimit, maxFeedInPower):
    if len(self._devices) == 0:
      return 0
    primaryMaxPower = self._devices[0].MaxPower
    primaryMinPower = self._devices[0].MinPower
    primaryPowerLimit = self._devices[0].PowerLimit
    secondaryMinPower = 0
    secondaryMaxPower = 0
    secondaryPowerLimit = 0
    limitSet = 0

    newLimit = max(newLimit, self._excessPower)
    newLimit = min(newLimit, maxFeedInPower)

    if self._dbusservice['/StartLimit'] > 0:
      newLimit = min(newLimit, self._dbusservice['/StartLimit'])

    if self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/BatteryLife/State') == 9:
      newLimit = min(newLimit, self._trottlingPower)

    if self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/Hub4Mode') != 3:
      newLimit = min(newLimit, self._dbusmonitor.get_value('com.victronenergy.hub4','/MaxDischargePower'))

    for i in range(1, len(self._devices)):
      if self._devices[i].Active == True:
        secondaryMaxPower += self._devices[i].MaxPower
        secondaryMinPower += self._devices[i].MinPower
        secondaryPowerLimit += self._devices[i].PowerLimit

    if newLimit > primaryMaxPower + secondaryMaxPower and primaryMaxPower + secondaryMaxPower == primaryPowerLimit + secondaryPowerLimit \
      or newLimit ==  primaryPowerLimit + secondaryPowerLimit:
        return primaryPowerLimit + secondaryPowerLimit
        
    self._powerLimitCounter = 0

    if newLimit >= primaryMaxPower + secondaryMaxPower:
      for device in self._devices:
        if device.Active == True:
          limitSet += device.setPowerLimit(device.MaxPower)
    
    elif newLimit <= primaryMinPower + secondaryMinPower:
      for device in self._devices:
        if device.Active == True:
          limitSet += device.setPowerLimit(device.MinPower)

    else:
      if primaryMaxPower >= newLimit - secondaryPowerLimit and primaryMinPower <= newLimit - secondaryPowerLimit:
        limitSet += self._devices[0].setPowerLimit(newLimit - secondaryPowerLimit)
        limitSet += secondaryPowerLimit
      
      elif newLimit <= (primaryMaxPower/2 + secondaryMinPower):
        for i in range(1, len(self._devices)):
          if self._devices[i].Active == True:
            limitSet += self._devices[i].setPowerLimit(self._devices[i].MinPower)
        limitSet += self._devices[0].setPowerLimit(newLimit - limitSet)
      
      elif newLimit >= (primaryMaxPower/2 + secondaryMaxPower):
        for i in range(1, len(self._devices)):
          if self._devices[i].Active == True:
            limitSet += self._devices[i].setPowerLimit(self._devices[i].MaxPower)
        limitSet += self._devices[0].setPowerLimit(newLimit - limitSet)
      
      else:
        for i in range(1, len(self._devices)):
          if self._devices[i].Active == True:
            p = int((newLimit - primaryMaxPower/2) * self._devices[i].MaxPower / secondaryMaxPower)
            limitSet += self._devices[i].setPowerLimit(p)
        limitSet += self._devices[0].setPowerLimit(newLimit - limitSet)

    return limitSet


  def _efficiency(self):
    return max(0.8, self._dbusservice['/Ac/Efficiency'] / 100)
  

  def _maxFeedInPower(self):
    maxFeedInPower = self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/MaxFeedInPower')
    if maxFeedInPower < 0: 
      return 9999
    else:
      return maxFeedInPower + self._dbusservice['/Ac/Power'] + self._gridPower


  def _actualLimit(self):
    actualLimit = 0
    for device in self._devices:
      actualLimit += device.PowerLimit
    
    return actualLimit


  def _availablePower(self):
    availablePower = 0
    for device in self._devices:
        availablePower += device.MaxPower
    return availablePower


  def _activePower(self):
    activePower = 0
    for device in self._devices:
        if device.Active == True:
          activePower += device.MaxPower
    return activePower


  def _disableFeedIn(self):
    if self._dbusservice['/Hub4/DisableFeedIn'] == 1:
      return True
    elif len(self._devices) == 0:
      return True
    elif self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/CGwacs/BatteryLife/State') == 9 \
    and self._trottlingPower == 0:
      return True
    elif self._inverterDcShutdown == True:
      return True
    elif self._dbusservice['/Mode'] in {1,4}:
      return True
    elif self._availablePower() == 0:
      return True
    return False


  def _refreshAcloads(self):
    availableAcLoads = []
    self._devices = []
    powerMeterService = None
    deviceName = ''

    for service in self._dbusmonitor.get_service_list('com.victronenergy.acload'):
      logging.log(EXTINFO,"acload: %s %s %s" % (service, self._dbusmonitor.get_value(service,'/CustomName'), self._dbusmonitor.get_value(service,'/DeviceInstance')))
      if self._dbusmonitor.get_value(service,'/CustomName') == None:
        deviceName = self._dbusmonitor.get_value(service,'/ProductName')
      else:
        deviceName = self._dbusmonitor.get_value(service,'/CustomName')

      if self._dbusmonitor.get_value(service,'/Ac/PowerLimit') == None:
        availableAcLoads.append(deviceName+':'+str(self._dbusmonitor.get_value(service,'/DeviceInstance')))
        if self._dbusmonitor.get_value(service,'/DeviceInstance') == self.settings['/PowerMeterInstance'] and self._dbusmonitor.get_value(service,'/Connected') == 1:
          powerMeterService = service
      else:
        self._addDevice(service, self._dbusmonitor)

    self._powerMeterService = powerMeterService
    
    if self._dbusservice == None and len(self._devices) > 0:
      self._dbusservice = new_service('com.victronenergy', 'vebus', 'MicroPlus', 'MicroPlus', self._devinst, self._devinst)
      self._initDbusservice()
    elif self._dbusservice != None and len(self._devices) == 0:
      self._dbusservice.__del__()
      self._dbusservice = None

    if self._dbusservice != None:
      self._dbusservice['/AvailableAcLoads'] = availableAcLoads
      self._dbusservice['/Ac/MaxPower'] = self._availablePower()


  def _addDevice(self,service,dbusmonitor):
    self._devices.append(DbusInverter(service, dbusmonitor))
    self._devices.sort(reverse=True, key=lambda x: x.MaxPower)


  def _MpptIsThrottling(self):
    for service in self._dbusmonitor.get_service_list('com.victronenergy.solarcharger'):
      if self._dbusmonitor.get_value(service,'/MppOperationMode') == 1:
        return True
    return False


  def _infoTopic(self):
    info = {}
    
    info['LoadPower'] = int(self._loadPower)
    info['GridPower'] = int(self._gridPower)
    info['InverterPower'] = int(self._dbusservice['/Ac/Power'])
    
    self._dbusservice['/Info'] = info
