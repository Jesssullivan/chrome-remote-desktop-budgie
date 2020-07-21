#!/usr/bin/python3
"""
Forceful server controls for chrome remote desktop.
Written by Jess Sullivan
@ https://github.com/Jesssullivan/chrome-remote-desktop-budgie
@ https://transscendsurvival.org/
"""

import logging
import platform
import subprocess
import sys
from shutil import which
import argparse
import atexit
import errno
import fcntl
import getpass
import grp
import hashlib
import json
import logging
import os
import pipes
import platform
import psutil
import pwd
import re
import signal
import socket
import subprocess
import syslog
import tempfile
import threading
import time


crd_path = '/opt/google/chrome-remote-desktop/chrome-remote-desktop'
goog_path = '/opt/google/chrome-remote-desktop/'


class remote(object):

    apt_depends = ['google-chrome', 'xserver-xorg-video-dummy', 'xserver-xorg-input-void']
    override = True
    verbose = True

    @staticmethod
    def _vprint(text):
        if remote.verbose:
            print(str(text))

    @classmethod
    def _is_installed(cls, cmd):
        cls._vprint(text='checking if ' + cmd + ' is present...')
        if not which(cmd):
            cls._vprint(text="didn't find " + cmd + '...')
            return False
        else:
            return True

    @classmethod
    def serve_install(cls):
        deb = ''

        for depend in remote.apt_depends:
            if not cls._is_installed(cmd=depend):
                subprocess.Popen('sudo apt-get install ' + depend + ' -y', shell=True).wait()

        """
        try:
            deb = sys.argv[1]
            remote._vprint('attempting to install ' + str(deb) + '...')

        except:
            remote._vprint('please provide chrome-remote-desktop .deb package as an argument to continue!')
            quit()

        cmd = str('sudo dpkg -i ' + deb)
        subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True).wait()
        time.sleep(.2)
        """

    @classmethod
    def get_display(cls):
        if remote.override:
            proc = subprocess.Popen('echo $DISPLAY', stdout=subprocess.PIPE, shell=True)
            result = proc.stdout.read().__str__()
            display_num = result.split(':')[1].split('\\')[0]
            remote._vprint(text='init display value read @ ' + display_num)
            return display_num
        else:
            remote._vprint(text='init display value set @ 0')
            return '0'

    @staticmethod
    def remote_sizes():
        if remote.override:
            return ("1600x1200,1600x900,1440x900,1366x768,1360x768,1280x1024,"
                    "1280x800,1280x768,1280x720,1152x864,1024x768,1024x600,"
                    "800x600,1680x1050,1920x1080,1920x1200,2560x1440,"
                    "2560x1600,3840x2160,3840x2560")
        else:
            return "1920x1080"

    @staticmethod
    def stop_crd():
        try:
            cmd = str(crd_path + ' --stop')
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            if 'denied' in proc.stdout.read().__str__():
                print('A command was denied, please reboot soon')
        except:
            print('A command was denied, please reboot soon')
            pass

    @staticmethod
    def start_crd():
        try:
            cmd = str(crd_path + ' --start')
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            if 'denied' in proc.stdout.read().__str__():
                print('A command was denied, please reboot soon')
        except:
            print('A command was denied, please reboot soon')
            pass

    @classmethod
    def update_opt_google(cls):
        cmd_a = 'sudo usermod -a -G chrome-remote-desktop $USER'
        cmd_b = str('sudo rm -rf ' + crd_path)
        cmd_c = str('sudo cp -rf *remote* ' + goog_path)
        cmds = [cmd_a, cmd_b, cmd_c]

        remote._vprint(text='syncing scripts....')

        remote.stop_crd()

        for cmd in cmds:
            try:
                subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True).wait()
                remote._vprint(text='executing ``` ' + str(cmd) + ' ```')
                time.sleep(.5)
            except:
                pass

    @staticmethod
    def crd_main():
        logging.basicConfig(level=logging.DEBUG,
                            format="%(asctime)s:%(levelname)s:%(message)s")
        sys.exit(crd_path)


if __name__ == "__main__":
    remote.serve_install()
    remote.update_opt_google()
    remote.crd_main()
