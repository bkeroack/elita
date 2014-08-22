__author__ = 'bkeroack'

from types import FunctionType
import functools
import logging
import collections

import type_check

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
    '''
    Recursively replaces char in nested dict keys with rep (for sanitizing input to mongo, for example)
    Modifies object in place! Returns None.
    '''
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

def paths_from_nested_dict(dict_obj, path=None):
    '''
    Given an arbitrarily-nested dict-like object, generate a list of unique tree path tuples.
    The last object in any path will be the deepest leaf value in that path.
    Ex:
    dict_obj = {
        'a': {
            0: 1,
            1: 2
        },
        'b': {
            'foo': 'bar'
        }
    }

    returns:
    [
        ('a', 0, 1),
        ('a', 1, 2),
        ('b', 'foo', 'bar')
    ]

    @type dict_obj: dict
    @type path: list
    '''
    assert not path or hasattr(path, '__getitem__')
    assert type_check.is_dictlike(dict_obj)
    assert not path or isinstance(path, list)
    path = path if path else list()
    unique_paths = list()
    for i, item in enumerate(dict_obj.iteritems()):
        if type_check.is_dictlike(item[1]):
            for nested_item in paths_from_nested_dict(item[1], path=path+[item[0]]):
                unique_paths.append(nested_item)
        else:
            unique_paths.append(tuple(path + [item[0]] + [item[1]]))
    return unique_paths

def flatten(list_obj):
    '''
    Given a nested n-dimensional list, return a flattened list
    '''
    assert list_obj
    assert isinstance(list_obj, collections.Iterable)
    for item in list_obj:
        if isinstance(item, collections.Iterable) and not type_check.is_string(item):
            for x in flatten(item):
                yield x
        else:
            yield item

def flatten_list(list_obj):
    '''
    Above without having to iterate
    '''
    return [x for x in flatten(list_obj)]
