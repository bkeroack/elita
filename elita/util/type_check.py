__author__ = 'bkeroack'

def is_dictlike(obj):
    return hasattr(obj, '__getitem__') and hasattr(obj, '__setitem__')

def is_optional_dict(obj):
    return not obj or is_dictlike(obj)