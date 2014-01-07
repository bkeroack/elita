from pyramid.view import view_config
import pyramid.exceptions
import pyramid.response
import logging
import urllib2
import pprint
import traceback
import sys

import models
import builds
import auth
import action
import gitservice

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
#lh = logging.StreamHandler(sys.stdout)
#lh.setLevel(logging.DEBUG)
#logger.addHandler(lh)

AFFIRMATIVE_SYNONYMS = ("true", "True", "TRUE", "yup", "yep", "yut", "yes", "yea", "aye", "please", "si", "sim")



class GenericView:
    def __init__(self, context, request, app_name="_global", permissionless=False, allow_pw_auth=False, is_action=False):
        self.required_params = {"GET": [], "PUT": [], "POST": [], "DELETE": []}  # { reqverb: [ params ] }
        logger.debug("{}: {} ; {}".format(self.__class__.__name__, context.__class__.__name__, request.subpath))
        self.req = request
        self.db = request.db
        self.datasvc = request.datasvc
        self.context = context
        if 'pretty' in self.req.params:
            if self.req.params['pretty'] in AFFIRMATIVE_SYNONYMS:
                self.req.override_renderer = "prettyjson"
        self.permissionless = permissionless
        self.is_action = is_action
        self.allow_pw_auth = allow_pw_auth
        self.setup_permissions(app_name)

    def get_created_datetime_text(self):
        return self.context.created_datetime.isoformat(' ') if hasattr(self.context, 'created_datetime') else None

    def deserialize_attributes(self):
        if 'attributes' in self.req.params and self.req.params['attributes'] in AFFIRMATIVE_SYNONYMS:
            try:
                attribs = self.req.json_body
            except:
                return False, self.Error("invalid attributes object (problem deserializing, bad JSON?)")
            return True, attribs
        else:
            return True, {}

    def call_action(self):
        g, p = self.check_params()
        if not g:
            return self.Error("Required parameter is missing: {}".format(p))
        if self.req.method == 'POST':
            if 'execute' in self.permissions:
                return self.POST()
            else:
                return self.Error('insufficient permissions')
        else:
            return self.UNKNOWN_VERB()

    def __call__(self):
        g, p = self.check_params()
        if self.is_action:
            return self.call_action()
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

        return r

    def check_params(self):
        if not self.permissionless and not self.allow_pw_auth:
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
            return
        if self.allow_pw_auth and 'auth_token' not in self.req.params:  # view sub-class responsible for verifying pw
            self.permissions = "read;write"
            return
        if 'auth_token' in self.req.params:
            token = self.req.params['auth_token']
            if self.is_action:
                self.permissions = auth.UserPermissions(self.datasvc.usersvc, token).get_action_permissions(app_name,
                                                                                      self.context.action_name)
            else:
                self.permissions = auth.UserPermissions(self.datasvc.usersvc, token).get_app_permissions(app_name)
        else:
            self.permissions = None

    def set_params(self, params):
        for t in params:
            self.required_params[t] = params[t]

    def return_action_status(self, action):
        return {"status": "ok", "action": action}


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



@view_config(context=pyramid.exceptions.HTTPNotFound, renderer='json')
class NotFoundView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, permissionless=True)
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


@view_config(context=Exception, renderer='json')
def ExceptionView(exc, request):
    exc_type, exc_obj, tb = sys.exc_info()
    logger.exception("")
    return {
        "fatal_application_error": {
            "unhandled_exception": traceback.format_exception(exc_type, exc_obj, tb)
        }
    }

class ApplicationContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        param = ["app_name"]
        self.set_params({"GET": [], "PUT": param, "POST": param, "DELETE": param})

    def validate_app_name(self, name):
        return name in self.datasvc.appsvc.GetApplications()

    def PUT(self):
        app_name = self.req.params["app_name"]
        self.datasvc.appsvc.NewApplication(app_name)
        return self.return_action_status({"new_application": {"name": app_name}})

    def DELETE(self):
        app_name = self.req.params["app_name"]
        if not self.validate_app_name(app_name):
            return self.Error("app name '{}' not found".format(app_name))
        self.datasvc.appsvc.DeleteApplication(app_name)
        return self.return_action_status({"delete_application": app_name})

    def GET(self):
        return {"applications": self.datasvc.appsvc.GetApplications()}


class ApplicationView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.app_name)
        self.set_params({"GET": [], "PUT": [], "POST": ["app_name"], "DELETE": []})

    def GET(self):
        return {"application": self.context.app_name,
                "created": self.get_created_datetime_text()}

class ActionContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)

    def GET(self):
        return {"application": self.context.parent,
                "actions": self.datasvc.jobsvc.GetAllActions(self.context.parent)}

class ActionView(GenericView):
    def __init__(self, context, request):
        self.app_name = context.app_name
        GenericView.__init__(self, context, request, app_name=self.app_name, is_action=True)
        params = {"GET": [], "PUT": [], "POST": [], "DELETE": []}
        for p in self.context.params:
            params[p] = self.context.params[p]
        self.set_params(params)

    def execute(self):
        if self.req.method not in self.context.params:
            return self.Error("not implemented")
        params = dict() #we need a plain dict so we can serialize to celery
        for p in self.req.params:
            params[p] = self.req.params[p]
        return self.status_ok(self.context.execute(params, self.req.method))

    def GET(self):
        return self.execute()
    def POST(self):
        return self.execute()
    def PUT(self):
        return self.execute()
    def DELETE(self):
        return self.execute()



class BuildContainerView(GenericView):
    def __init__(self, context, request):
        self.app_name = context.parent
        GenericView.__init__(self, context, request, app_name=self.app_name)
        self.set_params({"GET": [], "PUT": ["build_name"], "POST": ["build_name"], "DELETE": ["build_name"]})


    def validate_build_name(self, build_name):
        return build_name in self.datasvc.buildsvc.GetBuilds(self.app_name)

    def GET(self):
        return {"application": self.app_name,
                "builds": self.datasvc.buildsvc.GetBuilds(self.app_name)}

    def PUT(self):
        msg = list()
        build_name = self.req.params["build_name"]
        if '/' in build_name:
            build_name = str(build_name).replace('/', '-')
            msg.append("warning: forward slash in build name replaced by hyphen")
        if build_name in self.datasvc.buildsvc.GetBuilds(self.app_name):
            msg.append("build exists")
        attribs = self.deserialize_attributes()
        if not attribs[0]:
            return attribs[1]
        else:
            attribs = attribs[1]
        self.datasvc.buildsvc.NewBuild(self.app_name, build_name, attribs)
        return self.return_action_status({"new_build": {"application": self.app_name, "build_name": build_name,
                                                        "attributes": attribs, "messages": msg}})

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
        self.datasvc.buildsvc.DeleteBuild(self.app_name, build_name)
        return self.return_action_status({"delete_build": {"application": self.app_name, "build_name": build_name}})


class BuildView(GenericView):
    def __init__(self, context, request):
        self.app_name = context.app_name
        GenericView.__init__(self, context, request, app_name=self.app_name)
        self.set_params({"GET": [], "PUT": [], "POST": ["file_type"], "DELETE": ["file_name"]})
        self.build_name = None

    def upload_success_action(self):
        args = {
            'hook_parameters':
                {
                    'build_name': self.build_name,
                    'build_storage_info':
                        {
                          'storage_dir': self.bs_obj.storage_dir,
                          'filename': self.context.master_file,
                          'file_type': self.ftype
                        }
                }
        }
        return self.datasvc.actionsvc.hooks.run_hook(self.app_name, 'BUILD_UPLOAD_SUCCESS', args)

    def store_build(self, input_file, ftype):
        self.bs_obj = builds.BuildStorage(self.req.registry.settings['daft.builds.dir'],
                                          self.app_name, self.build_name, file_type=ftype, fd=input_file)
        if not self.bs_obj.validate():
            return self.Error("Invalid file type or corrupted file--check log")

        #try:
        fname = self.bs_obj.store()
        #except:
        #    return self.Error("error storing build or creating packages (see log)")
        logger.debug("BuildView: bs_results: {}".format(fname))
        self.context.master_file = fname
        self.context.packages['master'] = {'filename': fname, 'file_type': ftype}
        logger.debug("BuildView: context.packages: {}".format(self.context.packages))
        for k in self.context.packages:
            fname = self.context.packages[k]['filename']
            ftype = self.context.packages[k]['file_type']
            found = False
            for f in self.context.files:
                if f['path'] == fname:
                    found = True
            if not found:
                self.context.files.append({"file_type": ftype, "path": fname})
        self.context.stored = True
        self.datasvc.buildsvc.UpdateBuild(self.context)
        self.ftype = ftype

        return self.return_action_status({
            "build_stored": {
                "application": self.app_name,
                "build_name": self.build_name,
                "actions_result": self.upload_success_action()}
        })

    def direct_upload(self):
        logger.debug("BuildView: direct_upload")
        if 'build' in self.req.POST:
            fname = self.req.POST['build'].filename
            logger.debug("BuildContainer: PUT: filename: {}".format(fname))
            return self.store_build(self.req.POST['build'].file, self.req.params["file_type"])
        else:
            return self.Error("build data not found in POST body")

    def indirect_upload(self):
        logger.debug("BuildView: indirect_upload: downloading from {}".format(self.req.params['indirect_url']))
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
        if "package" in self.req.params:
            pkg = self.req.params['package']
            if pkg not in self.context.packages:
                return self.Error("package type '{}' not found".format(pkg))
            return pyramid.response.FileResponse(self.context.packages[pkg]['filename'], request=self.req,
                                                 cache_max_age=0)
        else:
            return {'application': self.context.app_name, 'build': self.context.build_name,
                'stored': self.context.stored, 'packages': self.context.packages,
                'files': self.context.files,
                'created_datetime': self.get_created_datetime_text(),
                'attributes': self.context.attributes}


class ServerContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": ['name'], "POST": [], "DELETE": ['name']})

    def GET(self):
        return {
            'servers': self.datasvc.serversvc.GetServers()
        }

    def PUT(self):
        name = self.req.params['name']
        attribs = self.deserialize_attributes()
        if not attribs[0]:
            return attribs[1]
        else:
            attribs = attribs[1]
        self.datasvc.serversvc.NewServer(name, attribs)
        return self.status_ok({
            "new_server": {
                "server_name": name,
                "attributes": attribs
            }
        })

    def DELETE(self):
        name = self.req.params['name']
        self.datasvc.serversvc.DeleteServer(name)
        return self.status_ok({
            "server_deleted": {
                "server_name": name
            }
        })

class ServerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        return {
            'server_name': self.context.name,
            'created_datetime': self.get_created_datetime_text(),
            'attributes': self.context.attributes,
            'gitdeploys': self.datasvc.serversvc.GetGitDeploys()
        }

class DeploymentContainerView(GenericView):
    pass

class DeploymentView(GenericView):
    pass

class GitProviderContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": ['name'], "POST": ['name'], "DELETE": []})

    def GET(self):
        return {
            'gitproviders': self.datasvc.gitsvc.GetGitProviders()
        }

    def PUT(self):
        name = self.req.params['name']
        try:
            info = self.req.json_body
        except:
            return self.Error("invalid gitprovider info object (problem deserializing, bad JSON?)")
        if 'auth' not in info or 'type' not in info or 'base_url' not in info:
            return self.Error("invalid gitprovider info object (valid JSON but missing one or more of: auth, type, base_url )")
        gp_type = info['type']
        auth = info['auth']
        base_url = info['base_url']
        if gp_type not in ('bitbucket', 'github'):
            return self.Error("gitprovider type not supported")
        self.datasvc.gitsvc.NewGitProvider(name, gp_type, auth)
        return self.status_ok({
            'new_gitprovider': {
                'name': name,
                'type': gp_type
            }
        })

    def POST(self):
        return self.PUT()

class GitProviderView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        return {
            'gitprovider': {
                'name': self.context.name,
                'type': self.context.type,
            }
        }

    def POST(self):
        new_doc = dict()
        if 'type' in self.req.params:
            pass

    def DELETE(self):
        self.datasvc.gitsvc.DeleteGitProvider(self.context.name)
        return self.status_ok({
            'delete_gitprovider': {
                'name': self.context.name
            }
        })

class GitRepoContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.parent)
        self.set_params({"GET": [], "PUT": ['name', 'existing'], "POST": ['name', 'existing'], "DELETE": []})

    def GET(self):
        return {
            'gitrepos': self.datasvc.gitsvc.GetGitRepos()
        }

    def PUT(self):
        existing = self.req.params['existing'] in AFFIRMATIVE_SYNONYMS
        name = self.req.params['name']
        try:
            gitrepo_info = self.req.json_body
        except:
            return self.Error("invalid gitrepo object (problem deserializing, bad JSON?)")
        if 'path' not in gitrepo_info:
            return self.Error("gitrepo path not found in JSON body")
        path = gitrepo_info['path']
        if 'gitprovider' in self.req.params:
            gitprovider = self.req.params['gitprovider']
        elif 'gitprovider' in gitrepo_info:
            gitprovider = gitrepo_info['gitprovider']
        else:
            return self.Error("No gitprovider given; specify in URL params or JSON body")
        ret = self.datasvc.gitsvc.NewGitRepo(self.context.parent, name, path, gitprovider)
        if ret['NewGitRepo'] != 'ok':
            return self.Error(ret)
        else:
            if not existing:
                gp_doc = self.datasvc.gitsvc.GetGitProvider(gitprovider)
                if gp_doc['type'] == 'bitbucket':
                    callable = gitservice.create_bitbucket_repo
                elif gp_doc['type'] == 'github':
                    callable = gitservice.create_github_repo
                else:
                    return self.Error("gitprovider type not supported ({})".format(gp_doc['type']))
                jid = action.run_async(self.datasvc, "CreateGitRepo", callable, ())
                msg = {
                    'task': 'create_repository',
                    'job_id': jid,
                    'status': 'async/running'
                }
            else:
                msg = {
                    'task': 'none'
                }
            return self.status_ok({
                'new_gitrepo': ret,
                'message': msg
            })

    def POST(self):
        return self.PUT()

class GitRepoView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.application)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        gp_doc = self.datasvc.Dereference(self.context.gitprovider)
        gp_doc = {k: gp_doc[k] for k in gp_doc if k[0] != '_'}
        return {
            'gitrepo': {
                'name': self.context.name,
                'application': self.context.pa,
                'path': self.context.path,
                'gitprovider': gp_doc
            }
        }


class GitDeployContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": ['name', 'application'], "POST": ['attributes'], "DELETE": []})
        self.server_name = context.parent

    def PUT(self):
        name = self.req.params['name']
        app = self.req.params['application']
        try:
            location_attribs = self.req.json_body
        except:
            return self.Error("invalid location/attributes object (problem deserializing, bad JSON?)")
        attribs = location_attribs['attributes'] if 'attributes' in location_attribs else {}
        if 'location' in location_attribs:
            location = location_attribs['location']
        else:
            return self.Error("invalid location object (valid JSON, 'location' key not found)")
        self.datasvc.gitdeploysvc.NewGitDeploy(name, app, self.server_name, location, attribs)


class GitDeployView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=self.context.application)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        return {
            'name': self.context.name,
            'server': self.context.server,
            'application': self.context.application,
            'attributes': self.context.attributes,
            'location': self.context.location
        }

class GlobalContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, permissionless=True)

    def GET(self):
        return {"global": ["users", "tokens"]}


class UserContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": ["username", "password"],
                         "POST": ["username", "password"], "DELETE": ["username"]})

    def PUT(self):
        name = self.req.params['username']
        pw = self.req.params['password']
        try:
            perms_attribs = self.req.json_body
        except:
            return self.Error("invalid user attributes object (problem deserializing, bad JSON?)")
        if "permissions" in perms_attribs:
            perms = perms_attribs['permissions']
            attribs = perms_attribs['attributes'] if 'attributes' in perms_attribs else dict()
            if auth.ValidatePermissionsObject(perms).run():
                self.datasvc.usersvc.NewUser(name, pw, perms, attribs)
                return self.status_ok({"user_created": {"username": name, "password": "(hidden)",
                                                        "permissions": perms, "attributes": attribs}})
            else:
                return self.Error("invalid permissions object (valid JSON but semantically incorrect)")
        else:
            return self.Error("invalid user attributes object (missing permissions)")

    def GET(self):
        return {"users": self.datasvc.usersvc.GetUsers()}

    def POST(self):
        return self.PUT()

    def DELETE(self):
        name = self.req.params['username']
        if name in self.datasvc.usersvc.GetUsers():
            self.datasvc.usersvc.DeleteUser(name)
            return self.status_ok({"user_deleted": {"username": name}})
        else:
            return self.Error("unknown user")

class JobView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        ret = {
            'job_id': str(self.context.id),
            'created_datetime': self.get_created_datetime_text(),
            'status': self.context.status,
        }
        if self.context.completed_datetime is not None:
            ret['completed_datetime'] = self.context.completed_datetime.isoformat(' ')
        if self.context.duration_in_seconds is not None:
            ret['duration_in_seconds'] = self.context.duration_in_seconds
        if 'results' in self.req.params:
            if self.req.params['results'] in AFFIRMATIVE_SYNONYMS:
                ret['results'] = self.datasvc.jobsvc.GetJobData(self.context.id)
        return ret

class JobContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": ["active"], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        active = self.req.params['active'] in AFFIRMATIVE_SYNONYMS
        return {"jobs": {"active": active, "job_ids": self.datasvc.jobsvc.GetJobs(active=active)}}


class UserView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, allow_pw_auth=True)  # allow both pw and auth_token auth
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})


    def status_ok_with_token(self, username):
        return self.status_ok({"username": username, "permissions": self.context.permissions,
                               "attributes": self.context.attributes,
                               "auth_token": self.datasvc.usersvc.GetUserTokens(username)})

    def change_password(self, new_pw):
        self.context.change_password(new_pw)
        self.datasvc.usersvc.SaveUser(self.context)

    def change_attributes(self, attribs):
        self.context.attributes = attribs
        self.datasvc.usersvc.SaveUser(self.context)

    def change_permissions(self, perms):
        self.context.permissions = perms
        self.datasvc.usersvc.SaveUser(self.context)

    def GET(self):  # return active
        if 'password' in self.req.params:
            if not self.context.validate_password(self.req.params['password']):
                return self.Error("incorrect password")
        elif 'auth_token' not in self.req.params:
            return self.Error("password or auth token required")
        name = self.context.name
        if len(self.datasvc.usersvc.GetUserTokens(name)) == 0:
            self.datasvc.usersvc.NewToken(name)
        return self.status_ok_with_token(name)

    def POST(self):
        if 'password' in self.req.params:
            if not self.context.validate_password(self.req.params['password']):
                return self.Error("incorrect password")
        update = self.req.params['update'] if 'update' in self.req.params else 'token'
        if update == "token":
            self.datasvc.usersvc.NewToken(self.context.name)
            return self.status_ok_with_token(self.context.name)
        elif update == "password":
            if "new_password" in self.req.params:
                self.change_password(self.req.params['new_password'])
                return self.status_ok("password changed")
            else:
                return self.Error("parameter new_password required")
        elif update == "attributes":
            try:
                attribs = self.req.json_body
            except:
                return self.Error("problem deserializing attributes object")
            self.change_attributes(attribs)
            return self.status_ok({"new_attributes": attribs})
        elif update == "permissions":
            try:
                perms = self.req.json_body
            except:
                return self.Error("problem deserializing permissions object (bad JSON?)")
            perms = perms['permissions'] if 'permissions' in perms else perms
            if auth.ValidatePermissionsObject(perms).run():
                self.change_permissions(perms)
                return self.status_ok({"new_permissions": perms})
            else:
                return self.Error("invalid permissions object (valid JSON but semantically incorrect)")
        else:
            return self.Error("incorrect request type '{}'".format(self.req.params['request']))


class TokenContainerView(GenericView):
    def __init__(self, context, request):
        #permissionless b/c the token is the secret. no need to supply token in URL and auth_token param
        GenericView.__init__(self, context, request, permissionless=True)
        self.set_params({"GET": ["username", "password"], "PUT": [], "POST": [], "DELETE": ["token"]})

    def GET(self):
        username = self.req.params['username']
        pw = self.req.params['password']
        if auth.UserPermissions(self.datasvc.usersvc, None).validate_pw(username, pw):
            tokens = self.datasvc.usersvc.GetUserTokens(username)
            if len(tokens) > 0:
                return self.status_ok({"username": username, "token": tokens})
            else:
                return self.Error("no token found for '{}'".format(username))
        else:
            return self.Error("incorrect password")

    def DELETE(self):
        token = self.req.params['token']
        if token in self.datasvc.usersvc.GetAllTokens():
            username = self.datasvc.usersvc.GetUserFromToken(token)
            self.datasvc.usersvc.DeleteToken(token)
            return self.status_ok({"token_deleted": {"username": username, "token": token}})
        else:
            return self.Error("unknown token")

class TokenView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)

    def GET(self):
        return {"token": self.context.token, "created": self.get_created_datetime_text(),
                "username": self.context.username}

    def DELETE(self):
        token = self.context.token
        user = self.context.username
        self.datasvc.usersvc.DeleteToken(token)
        return self.status_ok({"token_deleted": {"username": user, "token": token}})


#this is the default 'root' view that gets called for every request
@view_config(name="", renderer='json')
def Action(context, request):
    logger.debug("REQUEST: url: {}".format(request.url))
    logger.debug("REQUEST: context: {}".format(context.__class__.__name__))
    logger.debug("REQUEST: method: {}".format(request.method))
    logger.debug("REQUEST: params: {}".format(request.params))

    pp = pprint.PrettyPrinter(indent=4)
    if context.__class__.__name__ == 'Action':
        logger.debug("REQUEST: action")
        mobj = context
        cname = "Action"
    else:
        logger.debug("REQUEST: context.doc: {}".format(pp.pformat(context.doc)))
        cname = context.doc['_class']
        mobj = models.__dict__[cname](context.doc)

    logger.debug("Model class: {}".format(cname))

    view_class = globals()[cname + "View"]

    return view_class(mobj, request).__call__()

import pkg_resources
@view_config(name="about", renderer='json')
def About(request):
    return {'about': {'name': 'daft', 'version': pkg_resources.require("daft")[0].version}}




