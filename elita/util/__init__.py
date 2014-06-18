__author__ = 'bkeroack'

import string
from types import FunctionType
import functools
import logging

def log_wrapper(func):
    @functools.wraps(func)
    def log(*args, **kwargs):
        logging.debug("CALLING: {} (args: {}, kwargs: {}".format(func.__name__, args, kwargs))
        ret = func(*args, **kwargs)
        logging.debug("{} returned: {}".format(func.__name__, ret))
        return ret
    return log


class LoggingMetaClass(type):
    def __new__(mcs, classname, bases, class_dict):
        new_class_dict = dict()
        for attr_name, attr in class_dict.items():
            new_class_dict[attr_name] = log_wrapper(attr) if type(attr) == FunctionType else attr
        return type.__new__(mcs, classname, bases, new_class_dict)


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

def split_seq(seq, n):
    '''split iterable into n number of equal-length (approx) chunks'''
    newseq = []
    splitsize = 1.0/n*len(seq)
    for i in range(n):
        ns = seq[int(round(i*splitsize)):int(round((i+1)*splitsize))]
        if len(ns) > 0:
            newseq.append(ns)
    return newseq