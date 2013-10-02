from pyramid.config import Configurator
from pyramid_zodbconn import get_connection
from pyramid.renderers import JSON
from .models import appmaker
import daft_config

def root_factory(request):
    conn = get_connection(request)
    return appmaker(conn.root())


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    config = Configurator(root_factory=root_factory, settings=settings)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_renderer('prettyjson', JSON(indent=4))
    config.scan()

    daft_config.cfg = daft_config.DaftConfiguration()
    #just to make sure that the config file is found and valid
    daft_config.cfg.get_build_dir()

    return config.make_wsgi_app()
