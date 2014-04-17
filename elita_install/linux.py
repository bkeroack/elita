__author__ = 'bkeroack'

import shutil
import os
import os.path
import errno
import sys
from sh import service

def get_root_dir():
    return os.path.abspath(os.path.dirname(__file__))

def cp_file_checkperms(src, dest):
    try:
        shutil.copyfile(src, dest)
    except IOError as e:
        if e[0] == errno.EPERM:
            print("Insufficient permissions")
            sys.exit(1)

def mk_etc_dir_posix():
    if not os.path.isdir('/etc/elita'):
        try:
            os.mkdir('/etc/elita')
        except IOError as e:
            if e[0] == errno.EPERM:
                print("Insufficient permissions")
                sys.exit(1)

def cp_prod_ini_posix():
    ini_location = os.path.join(get_root_dir(), "production.ini")
    cp_file_checkperms(ini_location, '/etc/elita/production.ini')


def InstallUbuntu():

    mk_etc_dir_posix()
    cp_prod_ini_posix()

    upstart_location = os.path.join(get_root_dir(), "util", "upstart-elita.conf")
    cp_file_checkperms(upstart_location, '/etc/init/elita.conf')

    service("start", "elita")

    #create /etc/elita/
    #copy production.ini to /etc/elita/
    #copy upstart file to /etc/init/
    #service start elita


def InstallLinux():
    return InstallUbuntu()