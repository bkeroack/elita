__author__ = 'bkeroack'

import os
import platform
from clint.textui import puts, indent, colored

import linux
import darwin

# Autodetect platform, perform correct installation routine

def Install():
    os_name = os.name
    p_name = platform.system()

    puts("Installing Elita")

    with indent(4, quote=colored.blue('> ')):

        if os_name == 'posix':
            if p_name == 'Linux':
                puts("OS: {}".format(colored.green("Linux")))
                return linux.InstallLinux()
            elif p_name == 'Darwin':
                puts("OS: {}".format(colored.green("Darwin")))
                return darwin.InstallOSX()
            else:
                puts("{}: Unknown/unsupported POSIX-like OS: {}".format(colored.red("ERROR"), p_name))
        if os_name == 'nt':
            puts(colored.magenta("LOL Windows."))
            puts(colored.red("Only Linux/POSIX-like OSes are supported for Elita server installation."))
        else:
            puts("{}: Unsupported OS: {}".format(colored.red("ERROR"), p_name))
    return 1