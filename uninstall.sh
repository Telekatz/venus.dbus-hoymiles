#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SERVICE_NAME=$(basename $SCRIPT_DIR)

if  [ -e /service/$SERVICE_NAME ]
then
  rm /service/$SERVICE_NAME
  kill $(pgrep -f 'HMpvinverter.py')
  chmod a-x $SCRIPT_DIR/service/run
  kill $(pgrep -f 'HMpvinverter.py')  /dev/null 2> /dev/null
fi

# Clean the GUI
sed -i '/\/\* HM settings \*\//,/\/\* HM settings end \*\//d' /opt/victronenergy/gui/qml/PageAcInSetup.qml

if  [ -e /opt/victronenergy/gui/qml/OverviewGridParallel._qml ]
then
  cp /opt/victronenergy/gui/qml/OverviewGridParallel._qml /opt/victronenergy/gui/qml/OverviewGridParallel.qml 
fi

if  [ -e /opt/victronenergy/gui/qml/PageMain._qml ]
then
  cp /opt/victronenergy/gui/qml/PageMain._qml /opt/victronenergy/gui/qml/PageMain.qml
fi

rm -f /opt/victronenergy/gui/qml/OverviewGridParallel._qml
rm -f /opt/victronenergy/gui/qml/PageMain._qml
rm -f /opt/victronenergy/gui/qml/MultiHm.qml
rm -f /opt/victronenergy/gui/qml/PageHmSetup.qml
rm -f /opt/victronenergy/gui/qml/PageVebusHm.qml
rm -f /opt/victronenergy/themes/ccgx/images/overview-inverter-Hm.svg
rm -f /opt/victronenergy/themes/ccgx/images/overview-inverter-short-Hm.svg

svc -d /service/gui
sleep 1
svc -u /service/gui

# Remove install-script
grep -v "$SCRIPT_DIR/install.sh" /data/rc.local >> /data/temp.local
mv /data/temp.local /data/rc.local
chmod 755 /data/rc.local


