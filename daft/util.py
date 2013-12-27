__author__ = 'bkeroack'

import views
import random
import string

def debugLog(self, msg):
    views.logger.debug("{}: {}".format(self.__class__.__name__, msg))

def random_string(self, length, char_set=string.ascii_letters+string.digits):
    return ''.join(random.choice(char_set) for x in range(0, length))
