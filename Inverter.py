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
import time
import paho.mqtt.client as mqtt
import datetime

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

EXTINFO = 15

INVERTERLOOPRATE = 2

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
      self =  VeDbusService("{}.{}".format(base, type), dbusconnection(), register=False)
    else:
      self =  VeDbusService("{}.{}.{}_id{:02d}".format(base, type, physical,  id), dbusconnection(), register=False)
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

    self.register()
    
    return self


################################################################################
#                                                                              #
#   Inverter                                                                   #
#                                                                              #
################################################################################

class HmInverter:

  def __init__(self, serial):

    self.settings = None
    self._inverterLoopCounter = 0
    self._deviceinstance = 40
    self._role = 'acload'
    self._serial = serial
    self._inverterData = {}
    self._limitDeviationCounter = 0
    self.need_reinit = False
    self._dbus = dbusconnection()
    self._restartTimer = None
    self._checkState = False
    self._calibrationValues = None
    self._resendTimeout = 0
    self._dbusservice = None
    self.init()
    

  def init(self):
    # Ahoy
    self._inverterData[0] = {}
    self._inverterData[0]['ch0/P_AC'] = 0
    self._inverterData[0]['ch0/U_AC'] = 0
    self._inverterData[0]['ch0/I_AC'] = 0
    self._inverterData[0]['ch0/P_DC'] = 0
    self._inverterData[0]['ch0/F_AC'] = 0
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
      self._inverterData[1][f'{i}/current'] = 0

    self._initDbusMonitor()

    self._init_device_settings()
 
    VRMserial = self._dbusmonitor.get_value('com.victronenergy.system','/Serial') or 0

    self._MQTTName = "{}-{}".format(VRMserial,self._serial) 
    self._inverterPath = self.settings['/InverterPath']

    base = 'com.victronenergy'

    # Create dbus device
    if self.settings['/DTU'] == 0:
      dtu = "Ahoy"
    else:
      dtu = "OpenDTU"

    self._dbusservice = new_service(base, self._role, 'DTU', dtu, self._deviceinstance, self._deviceinstance)

    # Init the inverter
    self._initInverter()

    self._init_MQTT()

    # add _inverterLoop function
    gobject.timeout_add(1000 / INVERTERLOOPRATE, self._inverterLoop) 

    if self._restartTimer != None:
      gobject.source_remove(self._restartTimer)

    if self._role == 'acload':
      self._restartTimer = gobject.timeout_add_seconds(self._secondsToMidnight()+5, self._restartLoop)


  def _initInverter(self):
    maxPower = self.settings['/MaxPower']

    paths = {
      
      '/Ac/Energy/Forward':                 {'initial': None,     'textformat': _kwh},
      '/Ac/Power':                          {'initial': 0,        'textformat': _w},
      '/Ac/Frequency':                      {'initial': 0,        'textformat': _hz},
      '/Ac/Efficiency':                     {'initial': 0,        'textformat': _pct},
      '/Ac/PowerLimit':                     {'initial': maxPower, 'textformat': _w},
      '/Ac/MaxPower':                       {'initial': maxPower, 'textformat': _w},
      '/Ac/MinPower':                       {'initial': maxPower * 0.025, 'textformat': _w},

      '/Ac/L1/Current':                     {'initial': 0,        'textformat': _a},
      '/Ac/L1/Energy/Forward':              {'initial': None,     'textformat': _kwh},
      '/Ac/L1/Power':                       {'initial': 0,        'textformat': _w},
      '/Ac/L1/Voltage':                     {'initial': 0,        'textformat': _v},
      
      '/Ac/L2/Current':                     {'initial': 0,        'textformat': _a},
      '/Ac/L2/Energy/Forward':              {'initial': None,     'textformat': _kwh},
      '/Ac/L2/Power':                       {'initial': 0,        'textformat': _w},
      '/Ac/L2/Voltage':                     {'initial': 0,        'textformat': _v},

      '/Ac/L3/Current':                     {'initial': 0,        'textformat': _a},
      '/Ac/L3/Energy/Forward':              {'initial': None,     'textformat': _kwh},
      '/Ac/L3/Power':                       {'initial': 0,        'textformat': _w},
      '/Ac/L3/Voltage':                     {'initial': 0,        'textformat': _v},
      
      '/Dc/Power':                          {'initial': 0,        'textformat': _w},
      '/Dc/Current':                        {'initial': 0,        'textformat': _a},
      '/Dc/Voltage':                        {'initial': 0,        'textformat': _v},

      '/ErrorCode':                         {'initial': 0,        'textformat': None},
      '/DeviceName':                        {'initial': '',       'textformat': None},
      '/Temperature':                       {'initial': 0,        'textformat': _c},
      '/State':                             {'initial': 0,        'textformat': None},
    }

    # add path values to dbus
    self._dbusservice.add_path('/CustomName', self.settings['/Customname'], writeable=True, onchangecallback=self._customnameChanged)
    self._dbusservice.add_path('/AllowedRoles', ['pvinverter', 'acload'])
    self._dbusservice.add_path('/Role', self._role, onchangecallback=self._roleChanged,  writeable=True)
    
    for path, settings in paths.items():
      self._dbusservice.add_path(
        path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)

    if self._role == 'pvinverter':
      self._dbusservice.add_path('/Position', self.settings['/Position'], onchangecallback=self._handlechangedvalue,  writeable=True)
      self._dbusservice['/State'] = 2
    else:
      self._dbusservice.add_path('/Enabled', self.settings['/Enabled'], onchangecallback=self._handlechangedvalue,  writeable=True)
      self._dbusservice.add_path('/DisableFeedIn', 1, onchangecallback=self._handlechangedvalue,  writeable=True)
      self._dbusservice.add_path('/Restart', 0, onchangecallback=self._handlechangedvalue,  writeable=True)
      self._dbusservice.add_path('/Ac/CalibrationValues', self.settings['/CalibrationValues'], onchangecallback=self._handlechangedvalue,  writeable=True)
      self._dbusservice.add_path('/Ac/Calibration', self.settings['/Calibration'], onchangecallback=self._handlechangedvalue,  writeable=True)
      self._calibrationValues = self._getCalibrationArray(self._dbusservice['/Ac/CalibrationValues'])
      self._dbusservice['/Ac/MaxPower'] = self._getCalibratedMaxPower()

    self._dbusservice['/ProductId'] = 0xFFF1
    self._dbusservice['/FirmwareVersion'] = 0x482
    self._dbusservice['/ProductName'] = 'Hoymiles'
    self._dbusservice['/Connected'] = 1
    self._dbusservice['/Serial'] = self._serial


  def _roleChanged(self, path, value):
    if value not in ['pvinverter', 'acload']:
      return False
    self.settings['/ClassAndVrmInstance'] = '%s:%s' % (value, self._deviceinstance)
    self.need_reinit = True
    self.destroy()
    return True # accept the change


  def destroy(self):
    if self._dbusservice:
        self._dbusservice.__del__()
        self._dbusservice = None
    if self.settings:
        self.settings._settings = None
        self.settings = None
    self._MQTTclient.loop_stop()
    self._MQTTclient.disconnect()


  def _customnameChanged(self, path, val):
    self.settings['/Customname'] = val
    return True


  def _handlechangedvalue(self, path, value):
    logging.log(EXTINFO,"dbus_value_changed (Inverter %s): %s %s" % (self._serial, path, value,))
    if path == '/Position':
      self.settings['/Position'] = value
      return True # accept the change

    if path == '/Ac/PowerLimit':
      retVal = True
      if value == 0:
          if self._dbusmonitor.get_value('com.victronenergy.system','/VebusService') == None:
            logging.log(EXTINFO,"limit change rejected")
            return False
      elif value < self._dbusservice['/Ac/MinPower']:
        retVal = False
        value = self._dbusservice['/Ac/MinPower']
        self._dbusservice['/Ac/PowerLimit'] = value
      elif value > self._dbusservice['/Ac/MaxPower']:
        retVal = False
        value = self._dbusservice['/Ac/MaxPower']
        self._dbusservice['/Ac/PowerLimit'] = value
      logging.log(EXTINFO,"Limit %s changed: %s" % (self._serial, value,))
      if self._dbusservice['/State'] >= 1:
        self._inverterSetPower(value)
      return retVal

    if path == '/Enabled':
      #logging.log(EXTINFO,"dbus_value_changed: %s %s" % (path, value,))
      if value == 1:
        self.settings['/Enabled'] = 1
      else:
        self.settings['/Enabled'] = 0
      self._checkState = True

    if path == '/Ac/CalibrationValues':
      if value == '':
        self.settings['/CalibrationValues'] = value
        #logging.log(EXTINFO,"dbus_value_changed: %s %s" % (path, value,))
        self._calibrationValues = None
      else:
        array = self._getCalibrationArray(value)
        if array == None:
          return False
        else:
          self.settings['/CalibrationValues'] = value
          #logging.log(EXTINFO,"dbus_value_changed: %s %s" % (path, value,))
          self._calibrationValues = array
      self._dbusservice['/Ac/MaxPower'] = self._getCalibratedMaxPower()

    if path == '/Ac/Calibration':
      #logging.log(EXTINFO,"dbus_value_changed: %s %s" % (path, value,))
      self.settings['/Calibration'] = value
      self._dbusservice['/Ac/MaxPower'] = self._getCalibratedMaxPower()

    if path == '/DisableFeedIn':
      self._checkState = True

    if path == '/Restart':
      if value != 0:
        self._inverterRestart()
        return False

    return True # accept the change


  def _initDbusMonitor(self):
    dummy = {'code': None, 'whenToLog': 'configChange', 'accessLevel': None}
    dbus_tree = {
      'com.victronenergy.settings': { # Not our settings
        '/Settings/System/TimeZone' : dummy,
      },
      'com.victronenergy.system': {
        '/Serial': dummy,
        '/VebusService': dummy,
      },
    }
    self._dbusmonitor = DbusMonitor(dbus_tree)


  def _init_device_settings(self):
    if self.settings:
        return

    path = '/Settings/Devices/mInv_{}'.format(self._serial)
    def_inst = '%s:%s' % (self._role, self._deviceinstance)

    SETTINGS = {
        '/ClassAndVrmInstance':           [path + '/ClassAndVrmInstance', def_inst, 0, 0],
        '/Customname':                    [path + '/CustomName', 'HM-600', 0, 0],
        '/MaxPower':                      [path + '/MaxPower', 600, 0, 0],
        '/Phase':                         [path + '/Phase', 1, 1, 3],
        '/MqttUrl':                       [path + '/MqttUrl', '127.0.0.1', 0, 0],
        '/MqttPort':                      [path + '/MqttPort', 1883, 0, 0],
        '/MqttUser':                      [path + '/MqttUser', '', 0, 0],
        '/MqttPwd':                       [path + '/MqttPwd', '', 0, 0],
        '/InverterPath':                  [path + '/InverterPath', 'inverter/HM-600', 0, 0],
        '/DTU':                           [path + '/DTU', 0, 0, 1],
        '/InverterID':                    [path + '/InverterID', 0, 0, 9],
        '/Enabled':                       [path + '/Enabled', 1, 0, 1],
        '/Position':                      [path + '/Position', 0, 0, 2],
        '/AutoRestart':                   [path + '/AutoRestart', 0, 0, 1],
        '/CalibrationValues':             [path + '/CalibrationValues', '', 0, 0],
        '/Calibration':                   [path + '/Calibration', 0, 0, 1],
    }

    self.settings = SettingsDevice(self._dbus, SETTINGS, self._setting_changed)
    self._role, self._deviceinstance = self.get_role_instance()


  def get_role_instance(self):
    val = self.settings['/ClassAndVrmInstance'].split(':')
    return val[0], int(val[1])
  

  def _setting_changed(self, setting, oldvalue, newvalue):
    logging.info("setting changed, setting: %s, old: %s, new: %s" % (setting, oldvalue, newvalue))

    if setting == '/Customname':
      self._dbusservice['/CustomName'] = newvalue

    elif setting == '/MaxPower':
      self.settings['/MaxPower'] = newvalue
      self._dbusservice['/Ac/MaxPower'] = self._getCalibratedMaxPower()
      self._dbusservice['/Ac/MinPower'] = newvalue * 0.025
      
    elif setting == '/InverterPath':
      self._inverterPath = newvalue
      self._MQTT_connect()
    
    elif setting == '/MqttUrl':
      self.settings['/MqttUrl'] = newvalue
      self._MQTT_connect()

    elif setting == '/MqttPort':
      self.settings['/MqttPort'] = newvalue
      self._MQTT_connect()
     
    elif setting == '/MqttUser':
      self.settings['/MqttUser'] = newvalue
      self._MQTT_connect()
     
    elif setting == '/MqttPwd':
      self.settings['/MqttPwd'] = newvalue
      self._MQTT_connect()
      
    elif setting == '/Enabled':
      if self._role == 'acload':
        self._dbusservice['/Enabled'] = newvalue
        self._checkState = True

    elif setting == '/DTU':
      if self.settings['/DTU'] == 0:
        self._dbusservice['/Mgmt/Connection'] = "Ahoy"
      else:
        self._dbusservice['/Mgmt/Connection'] = "OpenDTU"
      self._MQTT_connect()


  def _checkInverterState(self):
    self._checkState = False
    if self._role == 'pvinverter':
      return
    
    if self._dbusservice['/State'] == 0: # Inverter is switched off
      # Switch on inverter if activated
      if self._dbusservice['/Enabled'] == 1 and self._dbusservice['/DisableFeedIn'] == 0:
        self._inverterSetLimit(self._dbusservice['/Ac/PowerLimit'], True)
        self._dbusservice['/State'] = 1
        self._inverterOn()
        return

      # Switch off inverter again if it is still running
      if self._dbusservice['/Ac/Power'] > 0 and self._resendTimeout == 0:
        self._inverterOff()

    else: # Inverter is switched on
      if  self._dbusservice['/State'] == 1:
        #Inverter starts
        if self._dbusservice['/Ac/Power'] == 0:
          if self._resendTimeout == 0:
            self._inverterOn()
        else:
          logging.log(EXTINFO,"Inverter %s start complete" % (self._serial))
          self._dbusservice['/State'] = 2
        return
      else:
        # Inverter is running
        if self._dbusservice['/Ac/Power'] == 0 and self._resendTimeout == 0:
          # Restart inverter
          self._inverterOn()

      # Switch off inverter if not activated
      if self._dbusservice['/Enabled'] == 0 or self._dbusservice['/DisableFeedIn'] == 1:
        self._inverterOff()
        self._dbusservice['/State'] = 0
        return
      

  def _inverterOn(self):
    logging.log(EXTINFO,"Inverter %s on" % (self._serial))
    self._MQTTclient.publish(self._inverterControlPath('power'), 1)
    self._resendTimeout = 60


  def _inverterOff(self):
    logging.log(EXTINFO,"Inverter %s off" % (self._serial))
    self._MQTTclient.publish(self._inverterControlPath('power'), 0)
    self._resendTimeout = 60


  def _inverterRestart(self):
    logging.log(EXTINFO,"Inverter %s restart" % (self._serial))
    self._MQTTclient.publish(self._inverterControlPath('restart'), 1)


  def _inverterSetLimit(self, newLimit, force=False):
    logging.log(EXTINFO,"_inverterSetLimit: %s" % (newLimit))
    if self._dbusservice['/State'] >= 0 or force:
      self._inverterSetPower(newLimit, force)
    self._dbusservice['/Ac/PowerLimit'] = newLimit


  def _inverterSetPower(self, power, force=False):
    newPower      = max(int(power), self._dbusservice['/Ac/MinPower'])
    currentPower  = int(self._dbusservice['/Ac/PowerLimit'] )
    
    logging.log(EXTINFO,"_inverterSetPower(%s): old %s, new %s" % (self._serial, currentPower, power))

    if newPower != currentPower or force == True:
      self._MQTTclient.publish(self._inverterControlPath('limit'), self._inverterFormatLimit(self._getCalibratedPower(newPower)))
      self._limitDeviationCounter = 0


  def _inverterLoop(self):
    try:
      if self.need_reinit == True:
        self.need_reinit = False
        self.init()
        return True
      
      # 0.5s interval
      self._inverterLoopCounter +=1
      self._inverterUpdate()

      if self._resendTimeout > 0:
        self._resendTimeout -= 1
      
      if self._limitDeviationCounter >= 3:
        logging.log(EXTINFO,"Inverter %s power deviation" % (self._serial))
        self._inverterSetPower(self._dbusservice['/Ac/PowerLimit'], True)

      # 20s interval
      if self._everySeconds(20) or self._checkState:
        self._checkInverterState()

      # 1min interval
      if self._everySeconds(60):
        if self._MQTTclient.is_connected() == False:
          logging.warning("MQTT not connected, try reconnect (SN:%s)" % (self._serial))
          self._MQTT_connect()

      # 5min interval
      if self._everySeconds(300):
        self._inverterLoopCounter = 0

        if self._dbusservice['/State'] > 1 and self._role == 'acload':
          self._inverterSetPower(self._dbusservice['/Ac/PowerLimit'], True)

    except Exception as e:
      logging.exception('Error at %s', '_inverterLoop', exc_info=e)

    return True


  def _inverterUpdate(self):
    try:

      pvinverter_phase = 'L' + str(self.settings['/Phase'])        

      if self.settings['/DTU'] == 0:
        # Ahoy
        powerAC     = self._inverterData[0]['ch0/P_AC']
        voltageAC   = self._inverterData[0]['ch0/U_AC']
        currentAC   = self._inverterData[0]['ch0/I_AC']
        frequency   = self._inverterData[0]['ch0/F_AC']
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
        powerAC     = self._inverterData[1]['0/power']
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
          currentDC -= self._inverterData[1][f'{i}/current']

      #send data to DBus
      for phase in ['L1', 'L2', 'L3']:
        pre = '/Ac/' + phase

        if phase == pvinverter_phase:
          self._dbusservice[pre + '/Voltage'] = voltageAC
          self._dbusservice[pre + '/Current'] = currentAC
          self._dbusservice[pre + '/Power'] = powerAC
          self._dbusservice[pre + '/Energy/Forward'] = yieldTotal

        else:
          self._dbusservice[pre + '/Voltage'] = None
          self._dbusservice[pre + '/Current'] = None
          self._dbusservice[pre + '/Power'] = None
          self._dbusservice[pre + '/Energy/Forward'] = None

      self._dbusservice['/Ac/Power'] = powerAC
      self._dbusservice['/Ac/Energy/Forward'] = yieldTotal
      self._dbusservice['/Ac/Efficiency'] = efficiency
      self._dbusservice['/Ac/Frequency'] = frequency

      self._dbusservice['/Dc/Current'] = currentDC
      self._dbusservice['/Dc/Voltage'] = volatageDC
      self._dbusservice['/Dc/Power'] = powerDC

      self._dbusservice['/Temperature'] = temperature

    except Exception as e:
      logging.exception('Error at %s', '_update', exc_info=e)

    return True


  def _init_MQTT(self):
    self._MQTTclient = mqtt.Client(self._MQTTName) # create new instance
    self._MQTTclient.on_disconnect = self._on_MQTT_disconnect
    self._MQTTclient.on_connect = self._on_MQTT_connect
    self._MQTTclient.on_message = self._on_MQTT_message
    self._MQTT_connect()


  def _MQTT_connect(self):
    try:
      self._MQTTclient.loop_stop()
      if self.settings['/MqttUser'] != '' and self.settings['/MqttPwd'] != '':
        self._MQTTclient.username_pw_set(self.settings['/MqttUser'], self.settings['/MqttPwd'])
      rc = self._MQTTclient.connect(self.settings['/MqttUrl'], self.settings['/MqttPort'])  # connect to broker
      logging.info("MQTT_connect to %s:%s rc %d"% (self.settings['/MqttUrl'], self.settings['/MqttPort'], rc))
      self._MQTTclient.loop_start()
    except Exception as e:
      logging.exception("Fehler beim connecten mit Broker")


  def _on_MQTT_disconnect(self, client, userdata, rc):
    logging.warning("Client Got Disconnected rc %d", rc)
    if rc != 0:
        logging.warning('Unexpected MQTT disconnection. Will auto-reconnect')
        try:
          logging.warning("Trying to Reconnect")
          client.connect(self.settings['/MqttUrl'],self.settings['/MqttPort'])
        except Exception as e:
          logging.exception("Fehler beim reconnecten mit Broker")
          logging.critical("Error in Retrying to Connect with Broker")
          logging.critical(e)


  def _on_MQTT_connect(self, client, userdata, flags, rc):
    if rc == 0:
        logging.info("MQTT connected (SN:%s)" % (self._serial))

        for k,v in self._inverterData[self.settings['/DTU']].items():
          client.subscribe(f'{self._inverterPath}/{k}')

    else:
        logging.warning("MQTT failed to connect, return code %d", rc)
        self._MQTTclient.loop_stop()
        self._MQTTclient.disconnect()


  def _on_MQTT_message(self, client, userdata, msg):
      logging.debug("MQTT message %s %s" % (msg.topic, msg.payload))

      try:
        if self._dbusservice == None:
          return       
        for k,v in self._inverterData[self.settings['/DTU']].items():
          if msg.topic == f'{self._inverterPath}/{k}':
            self._inverterData[self.settings['/DTU']][k] = float(msg.payload)
            if k in {'ch0/P_AC','0/power'} and self._dbusservice['/State'] >= 1 and self._role == 'acload':
              deviation = abs(self._dbusservice['/Ac/PowerLimit']-float(msg.payload))
              if deviation > 50:
                self._limitDeviationCounter = self._limitDeviationCounter + 1
              else:
                self._limitDeviationCounter = 0
            return

      except Exception as e:
          logging.exception('Error at %s', '_on_MQTT_message', exc_info=e)


  def _inverterControlPath(self, setting):
    if self.settings['/DTU'] == 0:
      # Ahoy
      ID = self.settings['/InverterID']
      path = '/'.join(self._inverterPath.split('/')[:-1])
      return path + f'/ctrl/{setting}/{ID}'
    else:
      # OpenDTU
      if setting == 'limit':
        setting = 'limit_nonpersistent_absolute'
      return self._inverterPath + f'/cmd/{setting}'


  def _inverterFormatLimit(self, limit):
    if self.settings['/DTU'] == 0:
      # Ahoy
      return '%sW' % limit
    else:
      # OpenDTU
      return '%s' % limit


  def _getCalibrationArray(self,value):
    try:
      retVal = []
      val = value.split(',')
      for x in val:
        y = x.split(':')
        vy = []
        vy.append(int(y[0]))
        vy.append(int(y[1]))
        retVal.append(vy)
      retVal.sort()
      if len(retVal) < 2:
        return None
      else:
        return retVal

    except:
      return None
  

  def _getCalibrationValues(self, setPower):
    try:

      if self._calibrationValues == None:
        return None,None
      
      if self._calibrationValues[0][1] > setPower:
        return self._calibrationValues[0],self._calibrationValues[1]
      
      if self._calibrationValues[len(self._calibrationValues)-1][1] <= setPower:
        return self._calibrationValues[len(self._calibrationValues)-2],self._calibrationValues[len(self._calibrationValues)-1]

      for i in range(0,len(self._calibrationValues)-1):
        if self._calibrationValues[i][1] <= setPower and self._calibrationValues[i+1][1] > setPower:
          return self._calibrationValues[i],self._calibrationValues[i+1]

    except:
      return None,None
    
    return None,None


  def _getCalibratedPower(self, setPower):
    if self._role == 'pvinverter':
      return setPower
    
    if self._dbusservice['/Ac/Calibration'] == 0:
      return setPower
    
    calValLow, calValHi = self._getCalibrationValues(setPower)
    if calValLow == None or calValHi == None:
      return setPower

    c = (calValHi[0]-calValLow[0])/(calValHi[1]-calValLow[1])
    calPower = ((setPower-calValLow[1]) * c) + calValLow[0]

    return calPower
  

  def _getCalibratedMaxPower(self):
    if self._role == 'pvinverter' or self.settings['/Calibration'] == 0 or self._calibrationValues == None:
      return self.settings['/MaxPower']
    
    if self._calibrationValues[len(self._calibrationValues)-1][0] == self.settings['/MaxPower']:
      return self._calibrationValues[len(self._calibrationValues)-1][1]
    else:
      return self.settings['/MaxPower']


  def _restartLoop(self):
    try:
      if self.settings['/AutoRestart'] == 1:
        self._inverterRestart()
    except Exception as e:
      logging.exception('Error at %s', '_restartLoop', exc_info=e)

    self._restartTimer = gobject.timeout_add_seconds(self._secondsToMidnight()+5, self._restartLoop)
    return False


  def _secondsToMidnight(self):
    tz = os.environ.get('TZ')
    os.environ['TZ'] = self._dbusmonitor.get_value('com.victronenergy.settings','/Settings/System/TimeZone')
    time.tzset()
    now = datetime.datetime.now()
    midnight = datetime.datetime.combine(now.date(), datetime.time.max)
    if tz == None:
      del os.environ['TZ']
    else:
      os.environ['TZ'] = tz
    time.tzset()
    return (midnight - now).seconds


  def _everySeconds(self,s):
    if self._inverterLoopCounter % (s * INVERTERLOOPRATE) == 0:
      return True
    else:
      return False


################################################################################
#                                                                              #
#   Main                                                                       #
#                                                                              #
################################################################################
  
def main():
  
  thread.daemon = True # allow the program to quit

  try:
      logging_level = logging.INFO

      #configure logging
      logging.basicConfig(  format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S',
                            level=logging_level,
                            handlers=[
                                logging.FileHandler("%s/current.log" % (os.path.dirname(os.path.realpath(__file__)))),
                                logging.StreamHandler()
                            ])

      from dbus.mainloop.glib import DBusGMainLoop
      # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
      DBusGMainLoop(set_as_default=True)
      
      logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
      mainloop = gobject.MainLoop()
      #start our main-service

      control = HmInverter(99)

      mainloop.run()

  except Exception as e:
    pass
    logging.critical('Error at %s', 'main', exc_info=e)

if __name__ == "__main__":
  main()