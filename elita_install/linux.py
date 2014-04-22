__author__ = 'bkeroack'

import shutil
import os
import os.path
import sys
import stat
import sh
from sh import useradd, chown
import logging
from clint.textui import puts, colored


ELITA_HOME = "/var/run/elita"
ELITA_LOG_DIR = "/var/log/elita"
ELITA_ETC = "/etc/elita"
ELITA_INITD = "/etc/init.d/elita"
ELITA_DEFAULTS = "/etc/default/elita"

LOGROTATE_DIR = "/etc/logrotate.d"

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
    ini_location = os.path.join(get_root_dir(), "util", "elita.ini")
    cp_file_checkperms(ini_location, os.path.join(ELITA_ETC, "elita.ini"))

def cp_initd_defaults():
    defaults_location = os.path.join(get_root_dir(), "util", "init.d-defaults")
    cp_file_checkperms(defaults_location, ELITA_DEFAULTS)

def cp_logrotate():
    if os.path.isdir(LOGROTATE_DIR):
        logrotate_location = os.path.join(get_root_dir(), "util", "logrotate")
        cp_file_checkperms(logrotate_location, os.path.join(LOGROTATE_DIR, "elita"))
    else:
        puts(colored.yellow("Logrotate directory not found!"))

def chmod_ax_initd():
    os.chmod(ELITA_INITD, stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

def chown_home_dir():
    chown("elita:elita", ELITA_HOME, R=True)  # use shell chown so we don't have to get the numeric UID/GID for 'elita'

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

    do_step("Copying logrotate script", cp_logrotate)

    do_step("Creating config directory: {}".format(ELITA_ETC), mk_dir, [ELITA_ETC])

    do_step("Creating running directory: {}".format(ELITA_HOME), mk_dir, [ELITA_HOME])

    do_step("Setting ownership on running directory", chown_home_dir)

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