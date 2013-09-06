from pyramid.config import Configurator
from pyramid_zodbconn import get_connection
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
    config.scan()

    daft_config.cfg = daft_config.DaftConfiguration()

    return config.make_wsgi_app()
