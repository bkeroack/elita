__author__ = 'bkeroack'

import shutil
import os
import os.path
import sys
from sh import service
import logging
from clint.textui import progress, puts, indent, colored

def get_root_dir():
    return os.path.abspath(os.path.dirname(__file__))

def cp_file_checkperms(src, dest):
    logging.debug("copying {} to {}".format(src, dest))
    try:
        shutil.copyfile(src, dest)
    except IOError:
        puts(colored.red("IO error (Insufficient permissions?)"))
        sys.exit(1)

def mk_etc_dir_posix():
    if not os.path.isdir('/etc/elita'):
        try:
            os.mkdir('/etc/elita')
        except IOError:
            puts(colored.red("IO error (Insufficient permissions?)"))
            sys.exit(1)

def cp_prod_ini_posix():
    ini_location = os.path.join(get_root_dir(), "util/elita.ini")
    cp_file_checkperms(ini_location, '/etc/elita/elita.ini')

def do_step(msg, func, params=[]):
    puts(msg + " ... ", newline=False)
    func(*params)
    puts(colored.green("DONE"))

def InstallUbuntu():

    puts("OS Flavor: Ubuntu")

    do_step("Making /etc/elita", mk_etc_dir_posix)

    do_step("Copying ini", cp_prod_ini_posix)

    upstart_location = os.path.join(get_root_dir(), "util", "upstart-elita.conf")

    do_step("Creating service (upstart)", cp_file_checkperms, [upstart_location, '/etc/init/elita.conf'])

    puts("Starting service...")
    service("start", "elita")

    puts(colored.green("Done!"))


def InstallLinux():
    return InstallUbuntu()