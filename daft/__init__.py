from pyramid.config import Configurator
from pyramid_zodbconn import get_connection
from pyramid.renderers import JSON
from . import models
import daft_config

from ZODB.FileStorage import FileStorage
from ZODB.DB import DB
import migrations

def root_factory(request):
    conn = get_connection(request)
    root = conn.root()
    return models.appmaker(root)


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    #run any necessary migrations
    storage = FileStorage('Data.fs')
    db = DB(storage)
    conn = db.open()
    root = conn.root()
    root = migrations.run_migrations(root)
    import transaction
    transaction.commit()
    db.close()

    config = Configurator(root_factory=root_factory, settings=settings)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_renderer('prettyjson', JSON(indent=4))
    config.scan()

    daft_config.cfg = daft_config.DaftConfiguration()
    #just to make sure that the config file is found and valid
    daft_config.cfg.get_build_dir()

    return config.make_wsgi_app()
