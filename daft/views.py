from pyramid.view import view_config
import pyramid.exceptions
import pyramid.response
import logging
import urllib2

import models
import daft_config
import builds
import action
import auth
import util


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)



class GenericView:
    def __init__(self, context, request, app_name="_global", permissionless=False):
        self.required_params = {"GET": [], "PUT": [], "POST": [], "DELETE": []}  # { reqverb: [ params ] }
        logging.debug("{}: {} ; {}".format(self.__class__.__name__, type(context), request.subpath))
        self.req = request
        self.context = context
        if 'pretty' in self.req.params:
            if self.req.params['pretty'] == "True" or self.req.params['pretty'] == "true":
                self.req.override_renderer = "prettyjson"
        self.permissionless = permissionless
        self.setup_permissions(app_name)

    def get_created_datetime_text(self):
        return self.context.created_datetime.isoformat(' ') if hasattr(self.context, 'created_datetime') else None

    def __call__(self):
        g, p = self.check_params()
        r = False
        if not g:
            return self.Error("Required parameter is missing: {}".format(p))
        if self.req.method == 'GET':
            if 'read' in self.permissions:
                r = self.GET()
        elif self.req.method == 'POST':
            if 'write' in self.permissions:
                r = self.POST()
        elif self.req.method == 'PUT':
            if 'write' in self.permissions:
                r = self.PUT()
        elif self.req.method == 'DELETE':
            if 'write' in self.permissions:
                r = self.DELETE()
        else:
            r = self.UNKNOWN_VERB()
        if not r:
            r = self.Error('insufficient permissions')

        self.persist()
        return r

    def check_params(self):
        if not self.permissionless:
            for p in self.required_params:
                self.required_params[p].append("auth_token")
        try:
            for p in self.required_params[self.req.method]:
                if p not in self.req.params:
                    return False, p
        except KeyError:  # invalid HTTP verb
            pass
        return True, None

    def setup_permissions(self, app_name):
        if self.permissionless:
            self.permissions = "read;write"
        else:
            if 'auth_token' in self.req.params:
                token = self.req.params['auth_token']
                self.permissions = auth.UserPermissions(token).get_permissions(app_name)
            else:
                self.permissions = None

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

    def UNKNOWN_VERB(self):
        return self.Error("unknown or unimplemented HTTP verb")


@view_config(context=models.RootApplication, renderer='templates/mytemplate.pt')
def root_view(request):
    return {'project': 'daft'}


@view_config(context=pyramid.exceptions.HTTPNotFound, renderer='json')
class NotFoundView(GenericView):
    def notfound(self):
        return self.Error("404 not found")
    def GET(self):
        return self.notfound()
    def POST(self):
        return self.notfound()
    def PUT(self):
        return self.notfound()
    def DELETE(self):
        return self.notfound()


#@view_config(context=Exception, renderer='json')
#def ExceptionView(exc, request):
#    return {"unhandled exception": exc}


class ApplicationContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, permissionless=True)
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
        GenericView.__init__(self, context, request, app_name=context.app_name)
        self.set_params({"GET": [], "PUT": [], "POST": ["app_name"], "DELETE": []})

    def GET(self):
        return {"application": self.context.app_name, "data": self.context.keys()}

class ActionContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)

    def GET(self):
        return {"application": self.context.app_name,
                "created_datetime": self.get_created_datetime_text(),
                "data": self.context.keys()}

class ActionView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})



class EnvironmentView(GenericView):
    pass


class BuildContainerView(GenericView):
    def __init__(self, context, request):
        self.app_name = context.app_name
        GenericView.__init__(self, context, request, app_name=self.app_name)
        self.set_params({"GET": [], "PUT": ["build_name"], "POST": ["build_name"], "DELETE": ["build_name"]})


    def validate_build_name(self, build_name):
        return build_name in self.context.keys()

    def GET(self):
        return {"application": self.app_name,
                "builds": self.context.keys()}

    def PUT(self):
        msg = list()
        build_name = self.req.params["build_name"]
        if '/' in build_name:
            build_name = str(build_name).replace('/', '-')
            msg.append("warning: forward slash in build name replaced by hyphen")
        if build_name in self.context:
            msg.append("build exists")
        subsys = self.req.params["subsys"] if "sybsys" in self.req.params else []
        build = models.Build(self.app_name, build_name, subsys)
        build["info"] = models.BuildDetail(build)
        self.context[build_name] = build
        return self.return_action_status({"new_build": {"application": self.app_name, "build_name": build_name,
                                                        "messages": msg}})

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
    def __init__(self, context, request):
        self.app_name = context.buildobj.app_name
        GenericView.__init__(self, context, request, app_name=self.app_name)

    def GET(self):
        return {'application': self.context.buildobj.app_name, 'build': self.context.buildobj.build_name,
                'stored': self.context.buildobj.stored, 'packages': self.context.buildobj.packages,
                'files': self.context.buildobj.files,
                'created_datetime': self.get_created_datetime_text()}


class BuildView(GenericView):
    def __init__(self, context, request):
        self.app_name = context.app_name
        GenericView.__init__(self, context, request, app_name=self.app_name)
        self.set_params({"GET": ["package"], "PUT": [], "POST": ["file_type"], "DELETE": ["file_name"]})
        self.build_name = None

    def upload_success_action(self):
        ra = action.RegisterActions()
        ra.register()
        return ra.run_action(self.app_name, 'BUILD_UPLOAD_SUCCESS', build_name=self.build_name)

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

        action_res = "ok" if self.upload_success_action() else "error"

        return self.return_action_status({
            "build_stored": {
                "application": self.app_name,
                "build_name": self.build_name,
                "actions_result": action_res}
        })

    def direct_upload(self):
        logging.debug("BuildView: direct_upload")
        fname = self.req.POST['build'].filename
        logging.debug("BuildContainer: PUT: filename: {}".format(fname))
        return self.store_build(self.req.POST['build'].file, self.req.params["file_type"])

    def indirect_upload(self):
        logging.debug("BuildView: indirect_upload: downloading from {}".format(self.req.params['indirect_url']))
        r = urllib2.urlopen(self.req.params['indirect_url'])
        return self.store_build(r, self.req.params["file_type"])

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


class GlobalContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, permissionless=True)

    def GET(self):
        return {"global": self.context.keys()}


class UserContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": ["username", "password"],
                         "POST": ["username", "password"], "DELETE": ["username"]})

    def PUT(self):
        name = self.req.params['username']
        pw = self.req.params['password']
        try:
            perms = self.req.json_body
        except:
            return self.Error("invalid permissions object (problem deserializing)")
        if auth.ValidatePermissionsObject(perms):
            self.context[name] = models.User(name, pw, perms, self.context.salt)
            return self.status_ok({"user_created": {"username": name, "password": "(hidden)", "permissions": perms}})
        else:
            return self.Error("invalid permissions object")

    def GET(self):
        return {"users": self.context.keys()}

    def POST(self):
        return self.PUT()

    def DELETE(self):
        name = self.req.params['username']
        if name in self.context:
            del self.context[name]
            return self.status_ok({"user_deleted": {"username": name}})
        else:
            return self.Error("unknown user")


class UserView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, permissionless=True)  # pw always req'd
        self.set_params({"GET": ["password"], "PUT": [], "POST": ["password"], "DELETE": ["password"]})

    def create_new_token(self, username):
        if auth.TokenUtils.new_token(username) is None:
            return self.Error('error creating token')

    def get_token_string(self, username):
        return auth.TokenUtils.get_token_by_username(username)

    def status_ok_with_token(self, username):
        return self.status_ok({"username": username, "auth_token": self.get_token_string(username)})

    def GET(self):  # return active
        if self.context.validate_password(self.req.params['password']):
            name = self.context.name
            if name not in models.root['app_root']['global']['tokens']:
                self.create_new_token(name)
            return self.status_ok_with_token(name)
        return self.Error("incorrect password")

    def POST(self):
        if self.context.validate_password(self.req.params['password']):
            self.create_new_token(self.context.name)
            return self.status_ok_with_token(self.context.name)
        return self.Error("incorrect password")


@view_config(name="", renderer='json')
def Action(context, request):
    logging.debug("Action")

    cname = context.__class__.__name__
    logging.debug(cname)
    view_class = globals()[cname + "View"]

    return view_class(context, request).__call__()




