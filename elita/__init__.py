from pyramid.config import Configurator
from pyramid.renderers import JSON

import pymongo

import models

def GetMongoClient(settings):
    assert settings
    client = pymongo.MongoClient(settings['elita.mongo.host'], int(settings['elita.mongo.port']), fsync=True,
                                 use_greenlets=True)
    assert client
    db = client[settings['elita.mongo.db']]
    assert db
    return db, db['root_tree'].find_one(), client

def DataStore(request):
    db, root, client = GetMongoClient(request.registry.settings)
    return db

def generate_root_tree(db):
    assert db
    tree = db['root_tree'].find_one()
    assert tree
    updater = models.RootTreeUpdater(tree, db)
    return models.RootTree(db, updater, tree, db.dereference(tree['_doc']))

def RootService(request):
    '''
    Get root tree.
    '''
    return generate_root_tree(request.db)

def DataService(request):
    return models.DataService(request.registry.settings, request.db, request.root)

def root_factory(request):
    #initialize request objects
    foo = request.db, request.datasvc
    return request.root

def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    @type settings: pyramid.registry.Registry
    """

    #data validator / migrations
    db, root, client = GetMongoClient(settings)
    dv = models.DataValidator(settings, root, db)
    dv.run()
    client.close()

    config = Configurator(root_factory=root_factory, settings=settings)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_renderer('prettyjson', JSON(indent=4))
    config.scan()

    config.add_request_method(DataStore, 'db', reify=True)
    config.add_request_method(RootService, 'root', reify=True)
    config.add_request_method(DataService, 'datasvc', reify=True)

    return config.make_wsgi_app()
