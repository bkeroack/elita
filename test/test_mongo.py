__author__ = 'bkeroack'

import pymongo
import bson
import multiprocessing
import copy
import time
import random

import elita.models

def setup_db():
    mc = pymongo.MongoClient(host='localhost', port=27017)
    db = mc['elita_testing']
    return mc, db

def clear_mocks(db):
    db['mock_objs'].remove()

mc, db = setup_db()

def _create_roottree():
    root = {
        '_lock': False,
        '_doc': bson.DBRef('dummy', bson.ObjectId()),
        'app': {
            'foo': {}
        }
    }
    db['root_tree'].remove()
    db['root_tree'].insert(root)
    clear_mocks(db)

test_obj = {
    'name': 'foobar',
    'attributes': {
        'a': 0,
        'b': 1
    }
}

test_obj2 = {
    'name': 'baz',
    'attributes': {
        'a': 2,
        'b': 3
    }
}

def _threadsafe_try_to_update_roottree(q, doc, path, collection, timeout=30, pause=0):
    ts_mc = pymongo.MongoClient(host='localhost', port=27017)
    ts_db = ts_mc['elita_testing']
    id = ts_db['mock_objs'].insert(doc, manipulate=False)
    ms = elita.models.MongoService(ts_db, timeout=timeout)
    time.sleep(pause)
    result = ms.update_roottree(path, collection, id)
    q.put(result, block=False)

def test_simple_roottree_lock():
    '''
    Test that root_tree locking code doesn't fail completely
    '''
    _create_roottree()

    ms = elita.models.MongoService(db)

    ms.lock_roottree()
    ms.release_lock_roottree()

def test_roottree_update():
    '''
    Test that a single root_tree update does what it should
    '''
    _create_roottree()

    id = db['mock_objs'].insert(test_obj, manipulate=False)

    ms = elita.models.MongoService(db)
    ms.update_roottree(('app', 'foo', 'mocks', 'foobar'), 'mock_objs', id)

    rt_list = [d for d in db['root_tree'].find()]

    assert len(rt_list) == 1
    assert '_lock' in rt_list[0]
    assert not rt_list[0]['_lock']
    assert 'mocks' in rt_list[0]['app']['foo']
    assert 'foobar' in rt_list[0]['app']['foo']['mocks']
    assert '_doc' in rt_list[0]['app']['foo']['mocks']['foobar']
    assert rt_list[0]['app']['foo']['mocks']['foobar']['_doc'].__class__.__name__ == 'DBRef'
    assert rt_list[0]['app']['foo']['mocks']['foobar']['_doc'].collection == 'mock_objs'
    assert rt_list[0]['app']['foo']['mocks']['foobar']['_doc'].id == id

def test_roottree_locked_update_fails():
    '''
    Test that with root_tree locked an attempted update fails
    '''
    _create_roottree()
    q = multiprocessing.Queue()
    ms = elita.models.MongoService(db)
    ms.lock_roottree()

    _threadsafe_try_to_update_roottree(q, doc=test_obj2, path=('app', 'foo', 'mocks', 'foobar2'),
                                       collection='mock_objs', timeout=2)    # low timeout so test doesn't take forever

    ms.release_lock_roottree()

    assert not q.get()


def test_roottree_simultaneous_updates():
    '''
    Test that multiple simultaneous root_tree updates all succeed with no data loss
    '''
    _create_roottree()
    p_list = list()
    q = multiprocessing.Queue()

    names = (
        'lecherousness',
        'undefinable',
        'agatizing',
        'jamesburg',
        'falling',
        'subtentacular',
        'acronymized',
        'chandleries',
        'croupiness',
        'rebleach',
        'unstartled',
        'unherbaceous'
    )

    doc_list = [copy.deepcopy(test_obj) for n in names]
    for n, d in zip(names, doc_list):
        d['name'] = n
        path = ('app', 'foo', 'mocks', n)
        p = multiprocessing.Process(target=_threadsafe_try_to_update_roottree,
                                    args=[q], kwargs={'doc': d, 'path': path, 'collection': 'mock_objs',
                                                           'timeout': 15, 'pause': random.random()/4})
        p_list.append(p)

    for p in p_list:
        p.start()

    for p in p_list:
        p.join(600)

    results = [q.get(block=False) for p in p_list]

    assert all(results)
    root = [d for d in db['root_tree'].find()]
    assert len(root) == 1
    root = root[0]
    assert all([n in root['app']['foo']['mocks'] for n in names])
    assert not root['_lock']

if __name__ == '__main__':
    test_simple_roottree_lock()
    test_roottree_update()
    test_roottree_locked_update_fails()
    test_roottree_simultaneous_updates()