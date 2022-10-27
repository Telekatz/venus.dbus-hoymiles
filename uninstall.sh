#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SERVICE_NAME=$(basename $SCRIPT_DIR)

rm /service/$SERVICE_NAME
kill $(pgrep -f 'HMpvinverter.py')
chmod a-x $SCRIPT_DIR/service/run
./restart.sh

cp /opt/victronenergy/gui/qml/OverviewGridParallel._qml /opt/victronenergy/gui/qml/OverviewGridParallel.qml 
cp /opt/victronenergy/gui/qml/PageMain._qml /opt/victronenergy/gui/qml/PageMain.qml

rm /opt/victronenergy/gui/qml/OverviewGridParallel._qml
rm /opt/victronenergy/gui/qml/PageMain._qml
rm /opt/victronenergy/gui/qml/MultiHm.qml
rm /opt/victronenergy/gui/qml/PageHmSetup.qml
rm /opt/victronenergy/gui/qml/PageVebusHm.qml
rm /opt/victronenergy/themes/ccgx/images/overview-inverter-Hm.svg
rm /opt/victronenergy/themes/ccgx/images/overview-inverter-short-Hm.svg

svc -t /service/gui
