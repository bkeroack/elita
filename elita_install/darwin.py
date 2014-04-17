__author__ = 'bkeroack'

import linux

def InstallOSX():
    linux.mk_etc_dir_posix()
    linux.cp_prod_ini_posix()

    print("Elita production.ini installed to /etc/elita/. Please run celery and pserve manually.")
