#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SERVICE_NAME=$(basename $SCRIPT_DIR)

# set permissions for script files
chmod a+x $SCRIPT_DIR/restart.sh
chmod 744 $SCRIPT_DIR/restart.sh

chmod a+x $SCRIPT_DIR/uninstall.sh
chmod 744 $SCRIPT_DIR/uninstall.sh

chmod a+x $SCRIPT_DIR/service/run
chmod 755 $SCRIPT_DIR/service/run

# create sym-link to run script in deamon
ln -s $SCRIPT_DIR/service /service/$SERVICE_NAME

# add install-script to rc.local to be ready for firmware update
filename=/data/rc.local
if [ ! -f $filename ]
then
    touch $filename
    chmod 755 $filename
    echo "#!/bin/bash" >> $filename
    echo >> $filename
fi

grep -qxF "$SCRIPT_DIR/install.sh" $filename || echo "$SCRIPT_DIR/install.sh" >> $filename

# update GUI
if ! [ -e /opt/victronenergy/gui/qml/OverviewGridParallel._qml ]
then
    cp /opt/victronenergy/gui/qml/OverviewGridParallel.qml /opt/victronenergy/gui/qml/OverviewGridParallel._qml 
fi

if ! [ -e /opt/victronenergy/gui/qml/PageMain._qml ]
then
    cp /opt/victronenergy/gui/qml/PageMain.qml /opt/victronenergy/gui/qml/PageMain._qml 
fi

ln -s -f $SCRIPT_DIR/qml/MultiHm.qml /opt/victronenergy/gui/qml/MultiHm.qml
ln -s -f $SCRIPT_DIR/qml/OverviewGridParallel.qml /opt/victronenergy/gui/qml/OverviewGridParallel.qml
ln -s -f $SCRIPT_DIR/qml/PageHmSetup.qml /opt/victronenergy/gui/qml/PageHmSetup.qml
ln -s -f $SCRIPT_DIR/qml/PageMain.qml /opt/victronenergy/gui/qml/PageMain.qml
ln -s -f $SCRIPT_DIR/qml/PageVebusHm.qml /opt/victronenergy/gui/qml/PageVebusHm.qml

ln -s -f $SCRIPT_DIR/qml/overview-inverter-Hm.svg /opt/victronenergy/themes/ccgx/images/overview-inverter-Hm.svg
ln -s -f $SCRIPT_DIR/qml/overview-inverter-short-Hm.svg /opt/victronenergy/themes/ccgx/images/overview-inverter-short-Hm.svg

svc -t /service/gui