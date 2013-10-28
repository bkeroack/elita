__author__ = 'bkeroack'

import random
import string


import logging

def debugLog(self, msg):
    logging.info("{}: {}".format(self.__class__.__name__, msg))

def random_string(self, length, char_set=string.ascii_letters+string.digits):
    return ''.join(random.choice(char_set) for x in range(0, length))