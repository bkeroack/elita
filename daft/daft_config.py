__author__ = 'bkeroack'

import ConfigParser


cfg = None

VERSION = "0.38"


class DaftConfiguration:
    def __init__(self):
        self.config = ConfigParser.SafeConfigParser()
        self.config.read('daft.cfg')

    def get_build_dir(self):
        return self.config.get('builds', 'dir')