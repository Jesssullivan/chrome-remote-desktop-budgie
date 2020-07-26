#!/bin/bash
# Forceful server controls for chrome remote desktop.
# @ https://github.com/Jesssullivan/chrome-remote-desktop-budgie
# @ https://transscendsurvival.org/

# permiss:
# sudo chmod u+x addsystemd.sh

# run:
# sudo ./addsystemd.sh


if [[ $EUID -ne 0 ]]; then

   echo "sudo is required to add crd_remote.service to systemd, aborting."

   exit 1

fi

echo "copying service to /etc/systemd/system/crd_remote.service..."

cp -R crd_remote.service /etc/systemd/system/crd_remote.service

echo "permissing service...."

chmod 644 /etc/systemd/system/crd_remote.service

echo "starting service...."

systemctl start crd_remote

echo "checking service...."

systemctl status crd_remote  >/dev/null

echo "done."
