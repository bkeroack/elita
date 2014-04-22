__author__ = 'bkeroack'

from elita import views
import random
import string

def debugLog(self, msg):
    views.logger.debug("{}: {}".format(self.__class__.__name__, msg))

def change_dict_keys(obj, char, rep):
    '''Recursively replaces char in nested dict keys with rep'''
    new_obj = obj
    for k in new_obj:
            if isinstance(k, list):
                change_dict_keys(k, char, rep)
            if isinstance(obj, dict):
                if isinstance(obj[k], dict):
                        change_dict_keys(obj[k], char, rep)
                if char in k:
                        obj[k.replace(char, rep)] = obj[k]
                        del obj[k]

