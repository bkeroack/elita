__author__ = 'bkeroack'

import linux

def InstallOSX():

    linux.cp_prod_ini_posix()

    print("Elita elita.ini installed to /etc/elita/. Please run celery and pserve manually.")
