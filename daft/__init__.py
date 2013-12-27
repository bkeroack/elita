from pyramid.config import Configurator
from pyramid.renderers import JSON

import pymongo

import models

def GetMongoClient(settings):
    client = pymongo.MongoClient(settings['daft.mongo.host'], int(settings['daft.mongo.port']))
    db = client[settings['daft.mongo.db']]
    return db, db['root_tree'].find_one(), client

def DataStore(request):
    db, root, client = GetMongoClient(request.registry.settings)
    return db

def RootService(request):
    tree = request.db['root_tree'].find_one()
    updater = models.RootTreeUpdater(tree, request.db)
    return models.RootTree(request.db, updater, tree, None)

def DataService(request):
    return models.DataService(request.registry.settings, request.db, request.root)

def root_factory(request):
    #initialize request objects
    foo = request.db, request.datasvc
    return request.root


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """

    #data validator / migrations
    db, root, client = GetMongoClient(settings)
    dv = models.DataValidator(root, db)
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
