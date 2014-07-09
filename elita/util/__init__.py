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


def split_seq(seq, n):
    '''split iterable into n number of equal-length (approx) chunks'''
    newseq = []
    splitsize = 1.0/n*len(seq)
    for i in range(n):
        ns = seq[int(round(i*splitsize)):int(round((i+1)*splitsize))]
        if len(ns) > 0:
            newseq.append(ns)
    return newseq

def set_dict_key(obj, path, value):
    '''
    In the dict-like obj (assumed to be a nested set of dicts), walk path and insert value.

    For example,

    obj = root_tree
    path = ('app', 'myapp', 'builds')
    value = { [build_reference_doc] }
    '''
    for k in path[:-1]:
        obj = obj.setdefault(k, {})
    obj[path[-1]] = value
