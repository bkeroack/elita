__author__ = 'bkeroack'

import os
import pkg_resources

from clint.arguments import Args
from clint.textui import puts, colored

import subcommands

config = {
    'host': 'localhost' if 'ELITA_HOST' not in os.environ else os.environ['ELITA_HOST'],
    'port': 2718 if 'ELITA_PORT' not in os.environ else os.environ['ELITA_PORT'],
    'secure': 'ELITA_SECURE' in os.environ,
    'ignore_cert': 'ELITA_IGNORE_CERT' in os.environ
}

sub_commands = {
    'about': subcommands.About
}

help_text = """
{title} {version}
=================

USAGE: elita [SUBCOMMAND] [OPTIONS]

SUBCOMMANDS:

{subcommands}
""".format(title=colored.green('elita'), version=colored.magenta(pkg_resources.require("elita")[0].version),
           subcommands="\n".join([k for k in sub_commands]))

def Command_Line_Client():

    args = Args().grouped

    for item in args:
        if item is '_':
            sc = args[item].all
            if not sc or len(sc) != 1 or sc[0] not in sub_commands:
                puts(help_text)
            else:
                sub_commands[sc[0]](config)