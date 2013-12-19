__author__ = 'bkeroack'

import ConfigParser


cfg = None

VERSION = "0.60"


class DaftConfiguration:
    def __init__(self):
        self.config = ConfigParser.SafeConfigParser()
        self.config.read('daft.cfg')

    def get_build_dir(self):
        return self.config.get('builds', 'dir')

    def get_mongo_server(self):
        return {
            'host': self.config.get('mongo', 'host'),
            'port': int(self.config.get('mongo', 'port')),
            'db': self.config.get('mongo', 'db')
        }
