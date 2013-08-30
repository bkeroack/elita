from pyramid.view import view_config
from .models import RootApplication, ApplicationContainer, Application, Build, Environment, Server, Deployment

import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


class GenericView:
    def __init__(self, context, request):
        logging.debug("{}: {} ; {}".format(self.__class__.__name__, type(context), request.subpath))
        self.req = request
        self.context = context

    def __call__(self):
        g, p = self.check_params()
        if not g:
            return self.Error("Required parameter is missing: {}".format(p))
        if self.req.method == 'GET':
            r = self.GET()
        elif self.req.method == 'POST':
            r = self.POST()
        elif self.req.method == 'PUT':
            r = self.PUT()
        elif self.req.method == 'DELETE':
            r = self.DELETE()
        else:
            r = None

        self.persist()
        return r

    def check_params(self):
        for p in self.required_params[self.req.method]:
            if p not in self.req.params:
                return False, p
        return True, None

    def set_params(self, params):
        self.required_params = dict()  # { reqverb: [ params ] }
        for t in params:
            self.required_params[t] = params[t]

    def return_action_status(self, action):
        return {"status": "ok", "action": action}

    def persist(self):
        import transaction
        transaction.commit()

    def status_ok(self, msg):
        return {'status': 'ok', 'message': msg}

    def Success(self):
        return {'status': 'success'}

    def Error(self, message):
        return {'status': 'error', 'message': message}

    def GET(self):
        return self.Error("not implemented")

    def POST(self):
        return self.Error("not implemented")

    def PUT(self):
        return self.Error("not implemented")

    def DELETE(self):
        return self.Error("not implemented")


@view_config(context=RootApplication, renderer='templates/mytemplate.pt')
def root_view(request):
    return {'project': 'daft'}

class ApplicationContainerView(GenericView):
    def __init__(self, context, request):
        param = ["app_name"]
        self.set_params({"GET": [], "PUT": param, "POST": param, "DELETE": param})
        GenericView.__init__(self, context, request)

    def PUT(self):
        app_name = self.req.params["app_name"]
        self.context[app_name] = Application(app_name)
        return self.return_action_status({"new_application": {"name": app_name}})

    def GET(self):
        return {"applications": self.context.keys()}


class ApplicationView(GenericView):
    def __init__(self, context, request):
        self.set_params({"GET": [], "PUT": [], "POST": ["app_name"], "DELETE": []})
        GenericView.__init__(self, context, request)

class EnvironmentView(GenericView):
    pass


class BuildView(GenericView):
    pass


class ServerView(GenericView):
    pass


class DeploymentView(GenericView):
    pass

@view_config(name="", renderer='json')
def Action(context, request):
    logging.debug("Action")

    cname = context.__class__.__name__
    logging.debug(cname)
    if cname == 'ApplicationContainer':
        logging.debug("...ApplicationContainer")
        return ApplicationContainerView(context, request).__call__()
    elif cname == 'Application':
        logging.debug("...Application")
        return App
    elif cname == 'Environment':
        return EnvironmentView(context, request).__call__()
    elif cname == "Build":
        return BuildView(context, request).__call__()
    elif cname == "Server":
        return ServerView(context, request).__call__()
    elif cname == "Deployment":
        return DeploymentView(context, request).__call__()



