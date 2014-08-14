__author__ = 'bkeroack'

import shutil
import os
import os.path
import sys
import stat
import sh
from sh import useradd, chown, chmod
import logging
from clint.textui import puts, colored, indent


ELITA_HOME = "/home/elita"
ELITA_LOG_DIR = "/var/log/elita"
ELITA_ETC = "/etc/elita"
ELITA_INITD = "/etc/init.d/elita"
ELITA_DEFAULTS = "/etc/default/elita"
ELITA_DATADIR = "/var/lib/elita"
ELITA_GITDEPLOY = "{}/gitdeploy".format(ELITA_DATADIR)
ELITA_BUILDS = "{}/builds".format(ELITA_DATADIR)

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

def chown_dir(dirname):
    chown("elita:elita", dirname, R=True)  # use shell chown so we don't have to get the numeric UID/GID for 'elita'

def create_user_and_group():
    try:
        useradd("elita", s="/bin/false", d=ELITA_HOME, G='root')    # root group so elita can run salt
    except:
        puts(colored.red("Error creating user/group elita!"))

def setup_nginx():
    nginx_path = '/etc/nginx/sites-available'
    elita_nginx_location = os.path.join(nginx_path, 'elita')
    puts('\n')
    with indent(4):
        if os.path.isdir(nginx_path):
            nginx_conf_location = os.path.join(get_root_dir(), "util", "nginx.conf")
            cp_file_checkperms(nginx_conf_location, elita_nginx_location)
            if not os.path.isdir('/etc/nginx/ssl'):
                mk_dir('/etc/nginx/ssl')
            puts(colored.magenta('Example nginx configuration copied to: {}'.format(elita_nginx_location)))
            puts(colored.magenta('To use:'))
            with indent(2, quote=colored.magenta('* ')):
                puts(colored.magenta('Add a symlink in /etc/nginx/sites-enabled'))
                puts(colored.magenta('Put your SSL certificate and key in /etc/nginx/ssl'))
                puts(colored.magenta('Restart nginx'))
            puts(colored.magenta('Elita will then be listening on port 2719 via SSL'))
        else:
            puts(colored.yellow('nginx not found. Install nginx and re-run'))
        puts('\n')

def create_salt_dirs():
    mk_dir('/srv')
    mk_dir('/srv/salt')
    mk_dir('/srv/salt/elita')
    mk_dir('/srv/salt/elita/files')
    mk_dir('/srv/salt/elita/files/win')
    mk_dir('/srv/salt/elita/files/linux')
    mk_dir('/srv/pillar')
    chown("elita:elita", "/srv/pillar", R=True)
    chown("elita:elita", "/srv/salt", R=True)

def copy_salt_files():
    git_setup_location = os.path.join(get_root_dir(), "util", "git_wrapper_setup.ps1")
    cp_file_checkperms(git_setup_location, '/srv/salt/elita/files/win/git_wrapper_setup.ps1')

def create_data_dirs():
    mk_dir(ELITA_DATADIR)
    mk_dir(ELITA_GITDEPLOY)
    mk_dir(ELITA_BUILDS)
    chown("elita:elita", ELITA_DATADIR, R=True)

def do_step(msg, func, params=[]):
    puts(msg + " ... ", newline=False)
    func(*params)
    puts(colored.green("DONE"))

def add_salt_client_acl():
    #find salt config
    #if exists, load it
    #deserialize the yaml
    #add/modify client_acl
    #serialize
    #save
    puts(colored.red("STUB"))

def InstallUbuntu():

    puts("OS Flavor: Ubuntu")

    do_step("Creating user and group 'elita'", create_user_and_group)

    do_step("Creating log directory: {}".format(ELITA_LOG_DIR), mk_dir, [ELITA_LOG_DIR])

    do_step("Setting ownership on log directory", chown_dir, [ELITA_LOG_DIR])

    do_step("Creating data directories", create_data_dirs)

    do_step("Copying logrotate script", cp_logrotate)

    do_step("Creating config directory: {}".format(ELITA_ETC), mk_dir, [ELITA_ETC])

    do_step("Setting ownership on config directory", chown_dir, [ELITA_ETC])

    do_step("Creating running directory: {}".format(ELITA_HOME), mk_dir, [ELITA_HOME])

    do_step("Creating Python egg cache directory", mk_dir, [os.path.join(ELITA_HOME, ".python-eggs")])

    do_step("Setting ownership on running directory", chown_dir, [ELITA_HOME])

    do_step("Copying ini", cp_prod_ini_posix)

    do_step("Copying init.d defaults", cp_initd_defaults)

    initd_location = os.path.join(get_root_dir(), "util", "init.d-elita")
    do_step("Copying init.d script", cp_file_checkperms, [initd_location, ELITA_INITD])

    do_step("Making init.d script executable", chmod_ax_initd)

    do_step("Creating salt base dirs if necessary", create_salt_dirs)

    do_step("Copying salt distributed files", copy_salt_files)

    do_step("Adding elita to salt client_acl", add_salt_client_acl)

    do_step("Setting up example nginx config", setup_nginx)

    puts("Starting service...")

    init_d = sh.Command(ELITA_INITD)
    init_d("start")

    puts(colored.yellow('Elita started and listening on http://localhost:2718/'))

    puts(colored.green("Done!"))


def InstallLinux():
    return InstallUbuntu()