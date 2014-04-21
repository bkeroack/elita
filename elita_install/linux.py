__author__ = 'bkeroack'

import shutil
import os
import os.path
import sys
import stat
import sh
from sh import useradd
import logging
from clint.textui import puts, colored


ELITA_HOME = "/var/run/elita"
ELITA_LOG_DIR = "/var/log/elita"
ELITA_ETC = "/etc/elita"
ELITA_INITD = "/etc/init.d/elita"
ELITA_DEFAULTS = "/etc/default/elita"

def get_root_dir():
    return os.path.abspath(os.path.dirname(__file__))

def cp_file_checkperms(src, dest):
    logging.debug("copying {} to {}".format(src, dest))
    try:
        shutil.copyfile(src, dest)
    except IOError:
        puts(colored.red("IO error (Insufficient permissions?)"))
        sys.exit(1)

def mk_dir(dirname):
    if not os.path.isdir(dirname):
        try:
            os.mkdir(dirname)
        except IOError:
            puts(colored.red("IO error (Insufficient permissions?)"))
            sys.exit(1)

def cp_prod_ini_posix():
    ini_location = os.path.join(get_root_dir(), "util/elita.ini")
    cp_file_checkperms(ini_location, '{}/elita.ini'.format(ELITA_ETC))

def cp_initd_defaults():
    defaults_location = os.path.join(get_root_dir(), "util/init.d-defaults")
    cp_file_checkperms(defaults_location, ELITA_DEFAULTS)

def chmod_ax_initd():
    os.chmod(ELITA_INITD, stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

def create_user_and_group():
    try:
        useradd("elita", s="/bin/false", d=ELITA_HOME)
    except:
        puts(colored.red("Error creating user/group elita!"))

def do_step(msg, func, params=[]):
    puts(msg + " ... ", newline=False)
    func(*params)
    puts(colored.green("DONE"))

def InstallUbuntu():

    puts("OS Flavor: Ubuntu")

    do_step("Creating user and group 'elita'", create_user_and_group)

    do_step("Creating log directory: {}".format(ELITA_LOG_DIR), mk_dir, [ELITA_LOG_DIR])

    do_step("Creating config directory: {}".format(ELITA_ETC), mk_dir, [ELITA_ETC])

    do_step("Copying ini", cp_prod_ini_posix)

    do_step("Copying init.d defaults", cp_initd_defaults)

    initd_location = os.path.join(get_root_dir(), "util", "init.d-elita")
    do_step("Copying init.d script", cp_file_checkperms, [initd_location, ELITA_INITD])

    do_step("Making init.d script executable", chmod_ax_initd)

    puts("Starting service...")

    init_d = sh.Command(ELITA_INITD)
    init_d("start")

    puts(colored.green("Done!"))


def InstallLinux():
    return InstallUbuntu()