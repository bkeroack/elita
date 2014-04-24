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


class IndentedTextParser:
    '''Written to parse our auto-generated ssh configs.
    Entries of the format are only indented to one level
    '''
    def __init__(self, path):
        self.file = open(path, 'r')
        self.parse()

    def cleanup(self):
        '''write new de-duped file'''
        pass

    def parse(self):
        '''parse into dict: { alias: { config_statement: [ list, of, params ] }}'''
        self.contents = dict()
        for l in self.file:
            current_section = None
            indentation_level = 0
            if l[0] in string.whitespace:
                if all([c in string.whitespace for c in l]):
                    continue  # if only whitespace, skip to next line
                for c in l:
                    if c in string.whitespace:
                        indentation_level += 1
            else:
                pass
