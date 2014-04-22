__author__ = 'bkeroack'

from clint.textui import puts, colored

from linux import ELITA_ETC, ELITA_LOG_DIR, ELITA_HOME
from linux import do_step, create_user_and_group, mk_dir, chown_dir, cp_prod_ini_posix

def InstallOSX():

    puts("OS Flavor: Darwin/OS X")

    do_step("Creating user and group 'elita'", create_user_and_group)

    do_step("Creating log directory: {}".format(ELITA_LOG_DIR), mk_dir, [ELITA_LOG_DIR])

    do_step("Setting ownership on log directory", chown_dir, [ELITA_LOG_DIR])

    do_step("Creating config directory: {}".format(ELITA_ETC), mk_dir, [ELITA_ETC])

    do_step("Setting ownership on config directory", chown_dir, [ELITA_ETC])

    do_step("Creating running directory: {}".format(ELITA_HOME), mk_dir, [ELITA_HOME])

    do_step("Setting ownership on running directory", chown_dir, [ELITA_HOME])

    do_step("Copying ini", cp_prod_ini_posix)

    puts(colored.yellow("Elita elita.ini installed to /etc/elita/. Please run celery and pserve manually."))

    puts(colored.green("Done!"))
