#!/usr/bin/env python

# import normal packages
import logging
import sys
import os
if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject
import configparser # for config/ini file

try:
  import thread   # for daemon = True  / Python 2.x
except:
  import _thread as thread   # for daemon = True  / Python 3.x
import dbus

#sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
#from vedbus import VeDbusService
#from settingsdevice import SettingsDevice
#from dbusmonitor import DbusMonitor


from multiprocessing import Process

from Inverter import HmInverter
from MicroPlus import MicroPlus
EXTINFO = 15

#class SystemBus(dbus.bus.BusConnection):
#    def __new__(cls):
#        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)


#class SessionBus(dbus.bus.BusConnection):
#    def __new__(cls):
#        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)


#def dbusconnection():
#    return SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()

def getConfig():
  config = configparser.ConfigParser()
  config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
  return config;


class clsProcess:
  serial = 0
  target = None
  process = None


class mainControl:

  def __init__(self):
    self.config = self._getConfig()
    self.procs = []

    if self.config.has_option('DEFAULT', 'InverterCount') == True:
      InverterCount = int(self.config["DEFAULT"]["InverterCount"])
    else:
      InverterCount = 1

    for i in range(1, InverterCount+1):
      proc = clsProcess()
      proc.serial = i
      proc.target = self._startInverter
      proc.process = Process(target=proc.target, args=(proc.serial,))
      self.procs.append(proc)

    proc = clsProcess()
    proc.serial = 0
    proc.target = self._startVebus
    proc.process = Process(target=proc.target, args=(proc.serial,))
    self.procs.append(proc)

    gobject.timeout_add_seconds(1, self._start)


  def _startInverter(self,serial):
    try:
      newDevice = HmInverter(serial)
      mainloop = gobject.MainLoop()
      mainloop.run()
    
    except Exception as e:
      pass
      logging.critical('Error at %s', 'main', exc_info=e)


  def _startVebus(self,serial):
    try:
      newDevice = MicroPlus()
      mainloop = gobject.MainLoop()
      mainloop.run()
    
    except Exception as e:
      pass
      logging.critical('Error at %s', 'main', exc_info=e)


  def _start(self):
    for proc in self.procs:
        proc.process.start()
    gobject.timeout_add_seconds(10, self._loop)
    return False


  def _loop(self):
    for proc in self.procs:
      if proc.process.is_alive() == False:
        logging.warning("Process stoped, restart process %s"% (proc.serial))
        proc.process = Process(target=proc.target, args=(proc.serial,))
        proc.process.start()
    return True


  def _getConfig(self):
    config = configparser.ConfigParser()
    config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
    return config


################################################################################
#                                                                              #
#   Main                                                                       #
#                                                                              #
################################################################################

def main():
  
  thread.daemon = True # allow the program to quit

  try:
      logging.addLevelName(EXTINFO, 'EXTINFO')
      config = getConfig()
      if config.has_option('DEFAULT', 'Logging') == True:
        logging_level = config["DEFAULT"]["Logging"]
      else:
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

      control = mainControl()

      mainloop.run()

  except Exception as e:
    pass
    logging.critical('Error at %s', 'main', exc_info=e)

if __name__ == "__main__":
  main()
