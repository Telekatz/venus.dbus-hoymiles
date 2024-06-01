#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
SERVICE_NAME=$(basename $SCRIPT_DIR)
GUI_DIR=/opt/victronenergy/gui/qml

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

# Backup GUI
if ! [ -e $GUI_DIR/PageAcInSetup._qml ]
then
    cp $GUI_DIR/PageAcInSetup.qml $GUI_DIR/PageAcInSetup._qml 
fi

if ! [ -e $GUI_DIR/OverviewGridParallel._qml ]
then
    mv $GUI_DIR/OverviewGridParallel.qml $GUI_DIR/OverviewGridParallel._qml 
fi

if ! [ -e /opt/victronenergy/gui/qml/PageMain._qml ]
then
    mv $GUI_DIR/PageMain.qml $GUI_DIR/PageMain._qml 
fi

# Patch GUI
patch=$SCRIPT_DIR/qml/PageAcInSetup_patch.qml
file=$GUI_DIR/PageAcInSetup.qml
if [ "$(cat $patch)" != "$(sed -n '/\/\* HM settings \*\//,/\/\* HM settings end \*\//p' $file )" ]; then
    sed -i '/\/\* HM settings \*\//,/\/\* HM settings end \*\//d'  $file
    line_number=$(grep -n "\/\* EM24 settings \*\/" $file | cut -d ":" -f 1)
    if ! [ -z "$line_number" ]; then
      line_number=$((line_number - 1))r
      echo "patching file $file"
      sed -i "$line_number $patch" $file
    else
      echo "Error patching file $file" 
    fi
fi

cp $GUI_DIR/OverviewGridParallel._qml $GUI_DIR/OverviewGridParallel.qml 
cp $GUI_DIR/PageMain._qml $GUI_DIR/PageMain.qml 

patch -p0 < $SCRIPT_DIR/qml/PageMain.diff
patch -p0 < $SCRIPT_DIR/qml/OverviewGridParallel.diff


ln -s -f $SCRIPT_DIR/qml/MultiHm.qml /opt/victronenergy/gui/qml/MultiHm.qml
ln -s -f $SCRIPT_DIR/qml/PageHmSetup.qml /opt/victronenergy/gui/qml/PageHmSetup.qml
ln -s -f $SCRIPT_DIR/qml/PageVebusHm.qml /opt/victronenergy/gui/qml/PageVebusHm.qml

ln -s -f $SCRIPT_DIR/qml/overview-inverter-Hm.svg /opt/victronenergy/themes/ccgx/images/overview-inverter-Hm.svg
ln -s -f $SCRIPT_DIR/qml/overview-inverter-short-Hm.svg /opt/victronenergy/themes/ccgx/images/overview-inverter-short-Hm.svg


svc -d /service/gui
sleep 1
svc -u /service/gui
