__author__ = 'bkeroack'

import os
import platform

import linux
import darwin

# Autodetect platform, perform correct installation routine

def Install():
    os_name = os.name
    p_name = platform.system()

    if os_name == 'posix':
        if p_name == 'Linux':
            return linux.InstallLinux()
        elif p_name == 'Darwin':
            return darwin.InstallOSX()
        else:
            print("Unknown POSIX-like os: {}".format(p_name))
    else:
        print("Unknown/Unsupported OS: {}; {}".format(os_name, p_name))
