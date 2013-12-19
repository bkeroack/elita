from pyramid.config import Configurator
from pyramid.renderers import JSON

import pymongo

import daft_config
import models

def DataStore(request):
    mdb_info = daft_config.cfg.get_mongo_server()
    client = pymongo.MongoClient(mdb_info['host'], mdb_info['port'], tz_aware=True)
    return client[mdb_info['db']]

def RootService(request):
    tree = request.db['root_tree'].find_one()
    updater = models.RootTreeUpdater(tree, request.db)
    return models.RootTree(request.db, updater, tree, None)

def DataService(request):
    return models.DataService(request.db, request.root)

def root_factory(request):
    #initialize request objects
    foo = request.db, request.datasvc
    return request.root


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    daft_config.cfg = daft_config.DaftConfiguration()
    #just to make sure that the config file is found and valid
    daft_config.cfg.get_build_dir()

    config = Configurator(root_factory=root_factory, settings=settings)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_renderer('prettyjson', JSON(indent=4))
    config.scan()

    config.add_request_method(DataStore, 'db', reify=True)
    config.add_request_method(RootService, 'root', reify=True)
    config.add_request_method(DataService, 'datasvc', reify=True)

    return config.make_wsgi_app()
