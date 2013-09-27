from pyramid.view import view_config
import pyramid.response
import logging
import random
import string
import requests

import models
import daft_config
import builds



logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


class Utility:
    def random_string(self, length, char_set=string.ascii_letters+string.digits):
        return ''.join(random.choice(char_set) for x in range(0, length))


class GenericView:
    def __init__(self, context, request):
        self.required_params = {"GET": [], "PUT": [], "POST": [], "DELETE": []}  # { reqverb: [ params ] }
        logging.debug("{}: {} ; {}".format(self.__class__.__name__, type(context), request.subpath))
        self.req = request
        self.context = context
        if 'pretty' in self.req.params:
            if self.req.params['pretty'] == "True" or self.req.params['pretty'] == "true":
                self.req.override_renderer = "prettyjson"

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


@view_config(context=models.RootApplication, renderer='templates/mytemplate.pt')
def root_view(request):
    return {'project': 'daft'}


class ApplicationContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        param = ["app_name"]
        self.set_params({"GET": [], "PUT": param, "POST": param, "DELETE": param})

    def validate_app_name(self, name):
        return name in self.context.keys()

    def PUT(self):
        app_name = self.req.params["app_name"]
        app = models.Application(app_name)
        app['environments'] = models.EnvironmentContainer(app_name)
        app['builds'] = models.BuildContainer(app_name)
        app['subsys'] = models.SubsystemContainer(app_name)
        app['action'] = models.ActionContainer(app_name)
        self.context[app_name] = app
        return self.return_action_status({"new_application": {"name": app_name}})

    def DELETE(self):
        app_name = self.req.params["app_name"]
        if not self.validate_app_name(app_name):
            return self.Error("app name '{}' not found".format(app_name))
        self.context.pop(app_name, None)
        return self.return_action_status({"delete_application": app_name})

    def GET(self):
        return {"applications": self.context.keys()}


class ApplicationView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": [], "POST": ["app_name"], "DELETE": []})

    def GET(self):
        return {"application": self.context.app_name, "data": self.context.keys()}

class ActionContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)

    def GET(self):
        return {"application": self.context.app_name, "data": self.context.keys()}

class ActionView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})



class EnvironmentView(GenericView):
    pass


class BuildContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": ["build_name"], "POST": ["build_name"], "DELETE": ["build_name"]})
        self.app_name = self.context.app_name

    def validate_build_name(self, build_name):
        return build_name in self.context.keys()

    def GET(self):
        return {"application": self.app_name, "builds": self.context.keys()}

    def PUT(self):
        build_name = self.req.params["build_name"]
        subsys = self.req.params["subsys"] if "sybsys" in self.req.params else []
        build = models.Build(self.app_name, build_name, subsys)
        self.context[build_name] = build
        return self.return_action_status({"new_build": {"application": self.app_name, "build_name": build_name}})

    def POST(self):
        build_name = self.req.params["build_name"]
        ok, err = self.validate_build_name(build_name)
        if not ok:
            return err
        return BuildView(self.context[build_name], self.req).POST()

    def DELETE(self):
        build_name = self.req.params["build_name"]
        if not self.validate_build_name(build_name):
            return self.Error("build name '{}' not found".format(build_name))
        self.context.pop(build_name, None)
        return self.return_action_status({"delete_build": {"application": self.app_name, "build_name": build_name}})


class BuildDetailView(GenericView):
    def GET(self):
        return {'application': self.context.buildobj.app_name, 'build': self.context.buildobj.build_name,
                'stored': self.context.buildobj.stored, 'packages': self.context.buildobj.packages,
                'files': self.context.buildobj.files}


class BuildView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": ["package"], "PUT": [], "POST": ["file_type"], "DELETE": ["file_name"]})
        self.app_name = self.context.app_name
        self.build_name = None

    def store_build(self, input_file, ftype):
        bs_obj = builds.BuildStorage(self.app_name, self.build_name, file_type=ftype, fd=input_file)
        if not bs_obj.validate():
            return self.Error("Invalid file type or corrupted file")

        #try:
        bs_results = bs_obj.store(packages=True)
        #except:
        #    return self.Error("error storing build or creating packages (see log)")
        logging.debug("BuildView: bs_results: {}".format(bs_results))
        self.context.master_file = bs_results[0]
        for k in bs_results[1]:
            self.context.packages[k] = bs_results[1][k]
        self.context.packages['master'] = {'filename': bs_results[0], 'file_type': ftype}
        logging.debug("BuildView: context.packages: {}".format(self.context.packages))
        for k in self.context.packages:
            fname = self.context.packages[k]['filename']
            ftype = self.context.packages[k]['file_type']
            self.context.files[fname] = ftype
        self.context.stored = True
        self.context["info"] = models.BuildDetail(self.context)

        return self.return_action_status({"build_stored": {"application": self.app_name, "build_name": self.build_name}})

    def direct_upload(self):
        logging.debug("BuildView: direct_upload")
        fname = self.req.POST['build'].filename
        logging.debug("BuildContainer: PUT: filename: {}".format(fname))
        return self.store_build(self.req.POST['build'].file, self.req.params["file_type"])

    def indirect_upload(self):
        logging.debug("BuildView: indirect_upload: downloading from {}".format(self.req.params['indirect_url']))
        r = requests.get(self.req.params['indirect_url'], stream=True)
        return self.store_build(r.raw, self.req.params["file_type"])

    def POST(self):
        self.build_name = self.context.build_name
        if self.req.params["file_type"] not in models.SupportedFileType.types:
            return self.Error("file type not supported")

        if "indirect_url" in self.req.params:
            return self.indirect_upload()
        else:
            return self.direct_upload()

    def GET(self):
        pkg = self.req.params['package']
        if pkg not in self.context.packages:
            return self.Error("package type '{}' not found".format(pkg))
        return pyramid.response.FileResponse(self.context.packages[pkg]['filename'], request=self.req, cache_max_age=0)


class ServerView(GenericView):
    pass


class DeploymentView(GenericView):
    pass

@view_config(name="", renderer='json')
def Action(context, request):
    logging.debug("Action")

    cname = context.__class__.__name__
    logging.debug(cname)
    view_class = globals()[cname + "View"]

    return view_class(context, request).__call__()




