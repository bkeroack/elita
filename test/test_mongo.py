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


def _threadsafe_direct_roottree_update(q, doc, path, collection, pause=0):
    ts_mc = pymongo.MongoClient(host='localhost', port=27017)
    ts_db = ts_mc['elita_testing']
    id = ts_db['mock_objs'].insert(doc)
    del doc['_id']
    path_dot_notation = '.'.join(path)
    root_tree_doc = {
        '_doc': bson.DBRef(collection, id)
    }
    time.sleep(pause)
    result = ts_db['root_tree'].update({}, {'$set': {path_dot_notation: root_tree_doc}})
    q.put(result['n'] == 1 and result['updatedExisting'] and not result['err'], block=False)


def test_roottree_update():
    '''
    Test that a single root_tree update does what it should
    '''
    _create_roottree()

    id = db['mock_objs'].insert(test_obj)
    del test_obj['_id']

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


def test_roottree_direct_update():
    '''
    Test that direct modification of root_tree without locking works
    '''

    _create_roottree()
    q = multiprocessing.Queue()

    _threadsafe_direct_roottree_update(q, test_obj, ('app', 'foo', 'mocks', 'ashley'), 'mock_objs')

    result = q.get()

    assert result
    root = [d for d in db['root_tree'].find()]
    assert len(root) == 1
    root = root[0]
    assert 'ashley' in root['app']['foo']['mocks']
    assert '_doc' in root['app']['foo']['mocks']['ashley']


def test_roottree_multiple_simultaneous_direct_updates():
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
        p = multiprocessing.Process(target=_threadsafe_direct_roottree_update,
                                    args=[q], kwargs={'doc': d, 'path': path, 'collection': 'mock_objs',
                                                      'pause': random.random()/4})
        p_list.append(p)

    for p in p_list:
        p.start()

    for p in p_list:
        p.join(600)

    results = [q.get() for p in p_list]

    assert all(results)
    root = [d for d in db['root_tree'].find()]
    assert len(root) == 1
    root = root[0]
    assert all([n in root['app']['foo']['mocks'] for n in names])
    assert not root['_lock']

def test_create_new_document():
    '''
    Test that creating a new document works
    '''
    insert_doc = copy.deepcopy(test_obj)
    insert_doc['name'] = 'swimming'
    ms = elita.models.MongoService(db)
    res = ms.create_new('mock_objs', 'swimming', 'Mock', insert_doc)

    assert res
    dlist = [d for d in db['mock_objs'].find({'name': 'swimming'})]
    assert len(dlist) == 1

if __name__ == '__main__':
    test_roottree_update()
    test_roottree_direct_update()
    test_roottree_multiple_simultaneous_direct_updates()
    test_create_new_document()
