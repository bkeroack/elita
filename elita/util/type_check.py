__author__ = 'bkeroack'

import collections
import json

def is_seq(obj):
    return isinstance(obj, collections.Sequence)

def is_optional_seq(obj):
    return not obj or is_seq(obj)

def is_dictlike(obj):
    return isinstance(obj, collections.Mapping)

def is_optional_dict(obj):
    return not obj or is_dictlike(obj)

def is_serializable(obj):
    '''
    Check is obj can be JSON serialized. We don't try to catch any exceptions because they generally provide better
    diagnostics
    '''
    json.dumps(obj)
    return True

def is_optional_str(obj):
    return not obj or isinstance(obj, str)


