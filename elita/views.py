from pyramid.view import view_config
import pyramid.exceptions
import pyramid.response
import logging
import pprint
import traceback
import sys
import fnmatch
import tempfile
import json
import socket

from elita.actions import action
import models
import builds
import auth
import elita.deployment.gitservice
import elita_exceptions
import elita.deployment.deploy

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

    def run_async(self, name, callable, args):
        jid = action.run_async(self.datasvc, name, callable, args)
        return {
            'task': name,
            'job_id': jid,
            'status': 'async/running'
        }

    def deserialize_attributes(self):
        if 'attributes' in self.req.params and self.req.params['attributes'] in AFFIRMATIVE_SYNONYMS:
            try:
                attribs = self.req.json_body
            except:
                return False, self.Error(400, "invalid attributes object (problem deserializing, bad JSON?)")
            return True, attribs
        else:
            return True, {}

    def do_patch(self, change_func, change_params, get_func, get_params):
        try:
            body = self.req.json_body
        except:
            return False, self.Error(400, "problem deserializing JSON body (bad JSON?)")
        keys = set(body.keys())
        cur_keys = set([k for k in self.context.doc if k[0] != '_'])
        if not keys.issubset(cur_keys):
            return False, self.Error(400, {"unknown modification keys": list(cur_keys - keys)})
        self.datasvc.appsvc.ChangeApplication(self.context.app_name, body)
        app_doc = self.datasvc.appsvc.GetApplication(self.context.app_name)
        return True, self.status_ok({
            'modified': {
                'changed': body,
                'new_object': app_doc
            }
        })

    def call_action(self):
        g, p = self.check_params()
        if not g:
            return self.MISSING_PARAMETER(p)
        if self.req.method == 'POST':
            if 'execute' in self.permissions:
                return self.POST()
            else:
                return self.UNAUTHORIZED()
        else:
            return self.UNIMPLEMENTED()

    def __call__(self):
        g, p = self.check_params()
        bad_verb = False
        if not g:
            return self.MISSING_PARAMETER(p)
        if self.req.method == 'GET':
            if 'read' in self.permissions:
                return self.GET()
        elif self.req.method == 'POST':
            if 'write' in self.permissions or (self.is_action and 'execute' in self.permissions):
                return self.POST()
        elif self.req.method == 'PUT' and not self.is_action:
            if 'write' in self.permissions:
                return self.PUT()
        elif self.req.method == 'DELETE' and not self.is_action:
            if 'write' in self.permissions:
                return self.DELETE()
        else:
            bad_verb = True
        if bad_verb:
            return self.UNKNOWN_VERB()
        return self.UNAUTHORIZED()

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
            if self.is_action and self.req.method == 'POST':
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

    def Error(self, code, message):
        body = {'status': 'error', 'error': message}
        return pyramid.response.Response(status_int=code, content_type="application/json", body=json.dumps(body))

    def GET(self):
        return self.UNIMPLEMENTED()

    def POST(self):
        return self.UNIMPLEMENTED()

    def PUT(self):
        return self.UNIMPLEMENTED()

    def DELETE(self):
        return self.UNIMPLEMENTED()

    def PATCH(self):
        return self.UNIMPLEMENTED()

    def UNKNOWN_VERB(self):
        return self.Error(501, "unknown/unsupported HTTP verb")

    def UNIMPLEMENTED(self):
        return self.Error(405, "HTTP verb '{}' not implemented for this resource".format(self.req.method))

    def UNAUTHORIZED(self):
        return self.Error(403, "insufficient permissions")

    def MISSING_PARAMETER(self, p):
        return self.Error(400, "Required parameter is missing: {}".format(p))


@view_config(context=pyramid.exceptions.HTTPNotFound, renderer='json')
class NotFoundView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, permissionless=True)
    def notfound(self):
        return self.Error(404, "not found (404)")
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
    body = {
        "status": "error",
        "error": {
            "unhandled_exception": traceback.format_exception(exc_type, exc_obj, tb)
        }
    }
    return pyramid.response.Response(status_int=500, content_type="application/json", body=json.dumps(body))

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
            return self.Error(400, "app name '{}' not found".format(app_name))
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
                "created": self.get_created_datetime_text(),
                self.context.app_name: self.datasvc.GetAppKeys(self.context.app_name)}

    def PATCH(self):
        pass

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
        self.set_params({"GET": [], "PUT": [], "POST": self.context.params, "DELETE": []})

    def execute(self):
        #we need a plain dict so we can serialize to celery
        params = {k: self.req.params[k] for k in self.req.params}
        return self.status_ok(self.context.execute(params))

    def GET(self):
        return {
            "application": self.context.app_name,
            "action": {
                "name": self.context.action_name,
                "post_parameters": self.context.details()['params']
            }
        }

    def POST(self):
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
        return self.return_action_status({
            "new_build": {
                "application": self.app_name,
                "build_name": build_name,
                "attributes": attribs,
                "messages": msg
            }
        })

    def POST(self):
        build_name = self.req.params["build_name"]
        ok, err = self.validate_build_name(build_name)
        if not ok:
            return err
        return BuildView(self.context[build_name], self.req).POST()

    def DELETE(self):
        build_name = self.req.params["build_name"]
        if not self.validate_build_name(build_name):
            return self.Error(400, "build name '{}' not found".format(build_name))
        self.datasvc.buildsvc.DeleteBuild(self.app_name, build_name)
        return self.return_action_status({"delete_build": {"application": self.app_name, "build_name": build_name}})


class BuildView(GenericView):
    def __init__(self, context, request):
        self.app_name = context.app_name
        GenericView.__init__(self, context, request, app_name=self.app_name)
        self.set_params({"GET": [], "PUT": [], "POST": ["file_type"], "DELETE": ["file_name"]})
        self.build_name = None

    def run_build_storage(self, func, arg):
        base_args = {
            'app': self.app_name,
            'build': self.build_name,
            'file_type': self.file_type
        }
        args = dict(base_args.items() + arg.items())
        msg = self.run_async('store_build', func, args)
        return self.return_action_status({
            "build_stored": {
                "application": self.app_name,
                "build_name": self.build_name,
                "message": msg
            }
        })

    def run_build_storage_direct(self, tempfile):
        return self.run_build_storage(builds.store_uploaded_build, {'temp_file': tempfile})

    def run_build_storage_indirect(self, uri):
        return self.run_build_storage(builds.store_indirect_build, {'uri': uri})

    def direct_upload(self):
        logger.debug("BuildView: direct_upload")
        if 'build' in self.req.POST:
            fname = self.req.POST['build'].filename
            logger.debug("BuildView: PUT: filename: {}".format(fname))
            fd, temp_file = tempfile.mkstemp()
            with open(temp_file, 'wb') as f:
                f.write(self.req.POST['build'].file.read(-1))
            return self.run_build_storage_direct(temp_file)
        else:
            return self.Error(400, "build data not found in POST body")

    def indirect_upload(self):
        return self.run_build_storage_indirect(self.req.params['indirect_url'])

    def POST(self):
        self.build_name = self.context.build_name
        if self.req.params["file_type"] not in models.SupportedFileType.types:
            return self.Error(400, "file type not supported")
        self.file_type = self.req.params["file_type"]

        if "indirect_url" in self.req.params:
            return self.indirect_upload()
        else:
            return self.direct_upload()

    def GET(self):
        if "package" in self.req.params:
            pkg = self.req.params['package']
            if pkg not in self.context.packages:
                return self.Error(400, "package type '{}' not found".format(pkg))
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
        self.set_params({"GET": [], "PUT": ['name', 'environment', 'existing'], "POST": [], "DELETE": ['name']})

    def GET(self):
        return {
            'servers': self.datasvc.serversvc.GetServers()
        }

    def PUT(self):
        name = self.req.params['name']
        environment = self.req.params['environment']
        attribs = self.deserialize_attributes()
        existing = self.req.params['existing'] in AFFIRMATIVE_SYNONYMS
        if not attribs[0]:
            return attribs[1]
        else:
            attribs = attribs[1]
        res = self.datasvc.serversvc.NewServer(name, attribs, environment)
        if not existing:
            msg = {"error": "server provisioning not implemented yet!"}
        else:
            msg = "none"
        if res['NewServer']['status'] == 'ok':
            return self.status_ok({
                "new_server": {
                    "server_name": name,
                    "environment": environment,
                    "attributes": attribs,
                    "message": msg
                }
            })
        else:
            return self.Error(500, res)

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
            'environment': self.context.environment,
            'attributes': self.context.attributes,
            'gitdeploys': self.datasvc.serversvc.GetGitDeploys(self.context.name)
        }

class EnvironmentView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        return {
            'environments': self.datasvc.serversvc.GetEnvironments()
        }

class DeploymentContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.parent)
        self.set_params({"GET": [], "PUT": [], "POST": ['build_name'], "DELETE": []})

    def GET(self):
        return {
            'application': self.context.parent,
            'deployments': self.datasvc.deploysvc.GetDeployments(self.context.parent)
        }

    def POST(self):
        app = self.context.parent
        build_name = self.req.params['build_name']
        if build_name not in self.datasvc.buildsvc.GetBuilds(app):
            return self.Error(400, "unknown build '{}'".format(build_name))
        try:
            body = self.req.json_body
        except:
            return self.Error(400, "invalid deployment object (problem deserializing, bad JSON?)")
        ok, msg = elita.deployment.deploy.validate_server_specs(body)
        if not ok:
            return self.Error(400, "invalid deployment object ({})".format(msg))
        if isinstance(body['servers'], str):
            servers = fnmatch.filter(self.datasvc.serversvc.GetServers(), body['servers'])
            if len(servers) == 0:
                return self.Error(400, "servers glob pattern doesn't match anything: {}".format(body['servers']))
        else:
            servers = body['servers']
        if isinstance(body['gitdeploys'], str):
            gitdeploys = fnmatch.filter(self.datasvc.gitsvc.GetGitDeploys(app), body['gitdeploys'])
            if len(gitdeploys) == 0:
                return self.Error(400, "gitdeploys glob pattern doesn't match anything: {}".format(body['gitdeploys']))
        else:
            gitdeploys = set(body['gitdeploys'])
            existing_gds = set(self.datasvc.gitsvc.GetGitDeploys(app))
            if not gitdeploys.issubset(existing_gds):
                diff = gitdeploys - existing_gds
                return self.Error(400, "unknown gitdeploys: {}".format(list(diff)))
            gitdeploys = list(gitdeploys)
        #verify that all servers have the requested gitdeploys initialized on them
        uninit_gd = dict()
        for gd in gitdeploys:
            gddoc = self.datasvc.gitsvc.GetGitDeploy(app, gd)
            init_servers = set(tuple(gddoc['servers']))
            req_servers = set(tuple(servers))
            if not init_servers.issuperset(req_servers):
                uninit_gd[gd] = list(req_servers - init_servers)
        if len(uninit_gd) > 0:
            return self.Error(400, {"message": "gitdeploy not initialized on servers", "servers": uninit_gd})
        dpo = self.datasvc.deploysvc.NewDeployment(app, build_name, body)
        d_id = dpo['NewDeployment']['id']
        msg = self.run_async('deploy_{}_{}'.format(app,  build_name), elita.deployment.deploy.run_deploy, {
            'application': app,
            'build_name': build_name,
            'servers': servers,
            'gitdeploys': gitdeploys,
            'deployment': d_id
        })
        self.datasvc.deploysvc.UpdateDeployment(app, d_id, {'status': 'running', 'job_id': msg['job_id']})
        return self.status_ok({
            'deployment': {
                'deployment_id': dpo['NewDeployment']['id'],
                'application': app,
                'build': build_name,
                'deployment': body,
                'message': msg
            }
        })


class DeploymentView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.application)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        return {
            'deployment': {
                'id': self.context.name,
                'job_id': self.context.job_id,
                'created_datetime': self.get_created_datetime_text(),
                'application': self.context.application,
                'deployment': self.context.deploy,
                'build': self.context.build_name,
                'status': self.context.status
            }
        }


class KeyPairContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name='_global')
        self.set_params({"GET": [], "PUT": ['name', 'key_type'], "POST": ['name', 'key_type'], "DELETE": ['name']})

    def GET(self):
        return {
            'keypairs': self.datasvc.keysvc.GetKeyPairs()
        }

    def PUT(self):
        name = self.req.params['name']
        key_type = self.req.params['key_type']
        try:
            info = self.req.json_body
        except:
            return self.Error(400, "invalid keypair info object (problem deserializing, bad JSON?)")
        attributes = info['attributes'] if 'attributes' in info else dict()
        if 'private_key' not in info:
            return self.Error(400, "private_key missing")
        else:
            private_key = info['private_key']
        if 'public_key' not in info:
            return self.Error(400, "public_key missing")
        else:
            public_key = info['public_key']
        ret = self.datasvc.keysvc.NewKeyPair(name, attributes, key_type, private_key, public_key)
        if ret['NewKeyPair']['status'] == 'ok':
            return self.status_ok({'new_keypair': {'name': name, 'key_type': key_type}})
        else:
            return self.Error(500, ret)

    def POST(self):
        return self.PUT()

    def DELETE(self):
        name = self.req.params['name']
        self.datasvc.keysvc.DeleteKeyPair(name)
        return self.status_ok({'delete_keypair': {'name': name}})


class KeyPairView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name='_global')
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        return {
            'keypair': {
                'created_datetime': self.get_created_datetime_text(),
                'name': self.datasvc.keysvc.GetKeyPair(self.context.name)
            }
        }

    def POST(self):
        try:
            info = self.req.json_body
        except:
            return self.Error(400, "invalid keypair info object (problem deserializing, bad JSON?)")
        self.datasvc.keysvc.UpdateKeyPair(self.context.name, info)
        return self.status_ok({'update_keypair': self.datasvc.keysvc.GetKeyPair(self.context.name)})

    def DELETE(self):
        self.datasvc.keysvc.DeleteKeyPair(self.context.name)
        return self.status_ok({'delete_keypair': {'name': self.context.name}})


class GitProviderContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": ['name'], "POST": ['name'], "DELETE": ['name']})

    def GET(self):
        return {
            'gitproviders': self.datasvc.gitsvc.GetGitProviders()
        }

    def PUT(self):
        name = self.req.params['name']
        try:
            info = self.req.json_body
        except:
            return self.Error(400, "invalid gitprovider info object (problem deserializing, bad JSON?)")
        if 'auth' not in info or 'type' not in info:
            return self.Error(400, "invalid gitprovider info object (valid JSON but missing one or more of: auth, type)")
        gp_type = info['type']
        auth = info['auth']
        if gp_type not in elita.deployment.gitservice.ValidRepoTypes.type_names:
            return self.Error(400, "gitprovider type not supported")
        self.datasvc.gitsvc.NewGitProvider(name, gp_type, auth)
        return self.status_ok({
            'new_gitprovider': {
                'name': name,
                'type': gp_type
            }
        })

    def POST(self):
        return self.PUT()

    def DELETE(self):
        name = self.req.params['name']
        if name in self.datasvc.gitsvc.GetGitProviders():
            self.datasvc.gitsvc.DeleteGitProvider(name)
            return self.status_ok({'delete_gitprovider': {'name': name}})
        else:
            return self.Error(400, "gitprovider '{}' not found".format(name))


class GitProviderView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        return {
            'gitprovider': {
                'created_datetime': self.get_created_datetime_text(),
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
        self.set_params({"GET": [], "PUT": ['name', 'existing', 'gitprovider', 'keypair'], "POST": ['name', 'existing'], "DELETE": ['name']})

    def GET(self):
        return {
            'application': self.context.parent,
            'gitrepos': self.datasvc.gitsvc.GetGitRepos(self.context.parent)
        }

    def PUT(self):
        existing = self.req.params['existing'] in AFFIRMATIVE_SYNONYMS
        gitprovider = self.req.params['gitprovider']
        keypair = self.req.params['keypair']
        name = self.req.params['name']

        if not existing:
            uri = None
            kp = self.datasvc.keysvc.GetKeyPair(keypair)
            gp_doc = self.datasvc.gitsvc.GetGitProvider(gitprovider)
            logger.debug("GitRepoContainerView: gp_doc: {}".format(gp_doc))
            repo_callable = elita.deployment.gitservice.create_repo_callable_from_type(gp_doc['type'])
            if not repo_callable:
                return self.Error(400, "gitprovider type not supported ({})".format(gp_doc['type']))
            msg = self.run_async("create_repository", repo_callable, {'gitprovider': gp_doc, 'name': name,
                                                                      'application': self.context.parent,
                                                                      'keypair': kp})
            ret = self.datasvc.gitsvc.NewGitRepo(self.context.parent, name, keypair, gitprovider, uri=uri)
            if ret['NewGitRepo'] != 'ok':
                return self.Error(500, {"error_NewGitRepo": ret, "message": msg})
        else:
            if 'uri' not in self.req.params:
                return self.MISSING_PARAMETER('uri')
            uri = self.req.params['uri']
            ret = self.datasvc.gitsvc.NewGitRepo(self.context.parent, name, keypair, gitprovider, uri=uri)
            if ret['NewGitRepo'] != 'ok':
                return self.Error(500, ret)
            gitrepo = self.datasvc.gitsvc.GetGitRepo(self.context.parent, name)
            msg = self.run_async("setup_local_gitdeploy", elita.deployment.gitservice.setup_local_gitrepo_dir, {
                'gitrepo': gitrepo
            })
        return self.status_ok({
            'new_gitrepo': ret,
            'message': msg
        })

    def POST(self):
        return self.PUT()

    def DELETE(self):
        name = self.req.params['name']
        if name in self.datasvc.gitsvc.GetGitRepos():
            self.datasvc.gitsvc.DeleteGitRepo(name)
            return self.status_ok({'delete_gitrepo': {'name': name}})
        else:
            return self.Error(400, "gitrepo '{}' not found".format(name))

class GitRepoView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.application)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        gp_doc = self.datasvc.Dereference(self.context.gitprovider)
        gp_doc = {k: gp_doc[k] for k in gp_doc if k[0] != '_'}
        gp_doc['auth']['password'] = "*****"
        return {
            'gitrepo': {
                'created_datetime': self.get_created_datetime_text(),
                'name': self.context.name,
                'application': self.context.application,
                'uri': self.context.uri if hasattr(self.context, 'uri') else None,
                'gitprovider': gp_doc
            }
        }

    def DELETE(self):
        name = self.context.name
        app = self.context.application
        self.datasvc.gitsvc.DeleteGitRepo(app, name)
        resp = {'delete_gitrepo': {'application': app, 'name': name}}
        if 'delete' in self.req.params and self.req.params['delete'] in AFFIRMATIVE_SYNONYMS:
            gp_doc = self.datasvc.Dereference(self.context.gitprovider)
            del_callable = elita.deployment.gitservice.delete_repo_callable_from_type(gp_doc['type'])
            if not del_callable:
                return self.Error(400, "git provider type not supported ({})".format(gp_doc['type']))
            msg = self.run_async("delete_repository", del_callable, {'gitprovider': gp_doc, 'name': self.context.name})
            resp['message'] = { 'delete_repository': msg}
        return self.status_ok(resp)


class GitDeployContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.parent)
        self.set_params({"GET": [], "PUT": ['name'], "POST": [], "DELETE": []})

    def GET(self):
        return {
            'application': self.context.parent,
            'gitdeploys': self.datasvc.gitsvc.GetGitDeploys(self.context.parent)
        }

    def PUT(self):
        name = self.req.params['name']
        app = self.context.parent
        try:
            location_attribs = self.req.json_body
        except:
            return self.Error(400, "invalid location/attributes object (problem deserializing, bad JSON?)")
        attribs = location_attribs['attributes'] if 'attributes' in location_attribs else {}
        options = location_attribs['options'] if 'options' in location_attribs else None
        actions = location_attribs['actions'] if 'actions' in location_attribs else None
        package = location_attribs['package'] if 'package' in location_attribs else 'master'
        if 'location' in location_attribs:
            location = location_attribs['location']
        else:
            return self.Error(400, "invalid location object (valid JSON, 'location' key not found)")
        try:
            assert 'path' in location
            assert 'gitrepo' in location
            assert 'default_branch' in location
        except AssertionError:
            return self.Error(400, "invalid location object: one or more of ('path', 'gitrepo', 'default_branch') not found")
        res = self.datasvc.gitsvc.NewGitDeploy(name, app, package, options, actions, location, attribs)
        if 'error' in res:
            return self.Error(500, {"NewGitDeploy": res})
        gd = self.datasvc.gitsvc.GetGitDeploy(app, name)
        msg = self.run_async("create_gitdeploy", elita.deployment.gitservice.create_gitdeploy, {'gitdeploy': gd})
        return self.status_ok({'create_gitdeploy': {'name': name, 'message': msg}})


class GitDeployView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.application)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        gddoc = self.datasvc.gitsvc.GetGitDeploy(self.context.application, self.context.name)
        return {
            'gitdeploy': {
                'created_datetime': self.get_created_datetime_text(),
                'name': gddoc['name'],
                'package': gddoc['package'],
                'application': gddoc['application'],
                'attributes': gddoc['attributes'],
                'servers': gddoc['servers'] if 'servers' in gddoc else "(not found)",
                'options': gddoc['options'],
                'actions': gddoc['actions'],
                'location': {
                    'path': gddoc['location']['path'],
                    'gitrepo': {
                        'name': gddoc['location']['gitrepo']['name'],
                        'gitprovider': {
                            'name': gddoc['location']['gitrepo']['gitprovider']['name'],
                            'type': gddoc['location']['gitrepo']['gitprovider']['type']
                        }
                    }
                }
            }
        }

    def check_servers_list(self, body):
        if "servers" not in body:
            return False, self.Error(400, "initialization requested but 'servers' not found")
        servers = body['servers']
        eservers = self.datasvc.serversvc.GetServers()
        if isinstance(servers, list):
            sset = set(eservers)
            sset_r = set(servers)
            if not sset.issuperset(sset_r):
                return False, self.Error(400, "unknown servers: {}".format(list(sset_r-sset)))
        else:
            sglob = servers
            servers = fnmatch.filter(eservers, servers)
            if len(servers) == 0:
                return False, self.Error(400, "no servers matched pattern: {}".format(sglob))
        self.servers = servers
        return True, None


    def update(self, body):
        keys = {'attributes', 'options', 'package', 'actions', 'location'}
        if "location" not in body:
            return self.Error(400, "invalid location object (valid JSON, 'location' key not found)")
        #verify no unknown/incorrect location keys
        body_keys = {k for k in body.keys()}
        if not keys.issuperset(body_keys):
            diff = body_keys - keys
            u_i = len(diff)
            word = "key"
            word += "s" if u_i > 1 else ""
            return self.Error(400, "invalid {}: {}".format(word, diff))
        self.datasvc.gitsvc.UpdateGitDeploy(self.context.application, self.context.name, body)
        gd = self.datasvc.gitsvc.GetGitDeploy(self.context.application, self.context.name)
        msg = self.run_async("create_gitdeploy", elita.deployment.gitservice.create_gitdeploy, {'gitdeploy': gd})
        return self.status_ok({'update_gitdeploy': {'name': self.context.name, 'object': body, 'message': msg}})

    def initialize(self, body):
        ok, err = self.check_servers_list(body)
        if not ok:
            return err
        #we need to get the fully dereferenced doc
        gddoc = self.datasvc.gitsvc.GetGitDeploy(self.context.application, self.context.name)
        msg = self.run_async('initialize_gitdeploy_servers', elita.deployment.gitservice.initialize_gitdeploy, {'gitdeploy': gddoc,
                                                                                               'server_list': self.servers})
        return self.status_ok({
            'initialize_gitdeploy': {
                'application': self.context.application,
                'name': self.context.name,
                'servers': self.servers,
                'msg': msg
            }
        })

    def deinitialize(self, body):
        ok, err = self.check_servers_list(body)
        if not ok:
            return err
        gddoc = self.datasvc.gitsvc.GetGitDeploy(self.context.application, self.context.name)
        msg = self.run_async('deinitialize_gitdeploy_servers', elita.deployment.gitservice.deinitialize_gitdeploy, {
            'gitdeploy': gddoc, 'server_list': self.servers
        })
        return self.status_ok({
            'deinitialize_gitdeploy': {
                'application': self.context.application,
                'name': self.context.name,
                'servers': self.servers,
                'msg': msg
            }
        })

    def POST(self):
        try:
            body = self.req.json_body
        except:
            return self.Error(400, "invalid body object (problem deserializing, bad JSON?)")
        if "initialize" in self.req.params and self.req.params['initialize'] in AFFIRMATIVE_SYNONYMS:
            return self.initialize(body)
        elif "deinitialize" in self.req.params and self.req.params['deinitialize'] in AFFIRMATIVE_SYNONYMS:
            return self.deinitialize(body)
        else:
            return self.update(body)

    def DELETE(self):
        gddoc = self.datasvc.gitsvc.GetGitDeploy(self.context.application, self.context.name)
        msg = self.run_async('remove_deinitialize_gitdeploy', elita.deployment.gitservice.remove_and_deinitialize_gitdeploy,
                             {'gitdeploy': gddoc})
        return self.status_ok({
            'delete_deinitialize_gitdeploy': {
                'application': gddoc['application'],
                'name': gddoc['name'],
                'servers': gddoc['servers'] if 'servers' in gddoc else list(),
                'msg': msg
            }
        })





class GlobalContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, permissionless=True)

    def GET(self):
        return {"global": self.datasvc.GetGlobalKeys()}


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
            return self.Error(400, "invalid user attributes object (problem deserializing, bad JSON?)")
        if "permissions" in perms_attribs:
            perms = perms_attribs['permissions']
            attribs = perms_attribs['attributes'] if 'attributes' in perms_attribs else dict()
            if auth.ValidatePermissionsObject(perms).run():
                self.datasvc.usersvc.NewUser(name, pw, perms, attribs)
                return self.status_ok({"user_created": {"username": name, "password": "(hidden)",
                                                        "permissions": perms, "attributes": attribs}})
            else:
                return self.Error(400, "invalid permissions object (valid JSON but semantically incorrect)")
        else:
            return self.Error(400, "invalid user attributes object (missing permissions)")

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
            return self.Error(400, "unknown user")

class JobView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def GET(self):
        ret = {
            'job_id': str(self.context.job_id),
            'created_datetime': self.get_created_datetime_text(),
            'status': self.context.status,
        }
        if self.context.completed_datetime is not None:
            ret['completed_datetime'] = self.context.completed_datetime.isoformat(' ')
        if self.context.duration_in_seconds is not None:
            ret['duration_in_seconds'] = self.context.duration_in_seconds
        if 'results' in self.req.params:
            if self.req.params['results'] in AFFIRMATIVE_SYNONYMS:
                ret['results'] = self.datasvc.jobsvc.GetJobData(self.context.job_id)
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
                return self.Error(403, "incorrect password")
        elif 'auth_token' not in self.req.params:
            return self.Error(403, "password or auth token required")
        name = self.context.name
        if len(self.datasvc.usersvc.GetUserTokens(name)) == 0:
            self.datasvc.usersvc.NewToken(name)
        return self.status_ok_with_token(name)

    def POST(self):
        if 'password' in self.req.params:
            if not self.context.validate_password(self.req.params['password']):
                return self.Error(403, "incorrect password")
        update = self.req.params['update'] if 'update' in self.req.params else 'token'
        if update == "token":
            self.datasvc.usersvc.NewToken(self.context.name)
            return self.status_ok_with_token(self.context.name)
        elif update == "password":
            if "new_password" in self.req.params:
                self.change_password(self.req.params['new_password'])
                return self.status_ok("password changed")
            else:
                return self.Error(400, "parameter new_password required")
        elif update == "attributes":
            try:
                attribs = self.req.json_body
            except:
                return self.Error(400, "problem deserializing attributes object")
            self.change_attributes(attribs)
            return self.status_ok({"new_attributes": attribs})
        elif update == "permissions":
            try:
                perms = self.req.json_body
            except:
                return self.Error(400, "problem deserializing permissions object (bad JSON?)")
            perms = perms['permissions'] if 'permissions' in perms else perms
            if auth.ValidatePermissionsObject(perms).run():
                self.change_permissions(perms)
                return self.status_ok({"new_permissions": perms})
            else:
                return self.Error(400, "invalid permissions object (valid JSON but semantically incorrect)")
        else:
            return self.Error(400, "incorrect request type '{}'".format(self.req.params['request']))

class UserPermissionsView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, allow_pw_auth=True)
        self.set_params({"GET": [], "PUT": [], "POST": [], "DELETE": []})

    def compute_app_perms(self):
        return auth.UserPermissions(self.datasvc.usersvc, None, datasvc=self.datasvc).get_allowed_apps(self.context
                                                                                                       .username)

    def compute_action_perms(self):
        return auth.UserPermissions(self.datasvc.usersvc, None, datasvc=self.datasvc).get_allowed_actions(self
                                                                                                          .context
                                                                                                          .username)

    def compute_server_perms(self):
        return auth.UserPermissions(self.datasvc.usersvc, None, datasvc=self.datasvc).get_allowed_servers(self
                                                                                                          .context
                                                                                                          .username)

    def GET(self):
        return {
            'username': self.context.username,
            'applications': self.compute_app_perms(),
            'actions': self.compute_action_perms(),
            'servers': self.compute_server_perms()
        }


class TokenContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name='_global')
        self.set_params({"GET": ["username", "password"], "PUT": [], "POST": [], "DELETE": ["token"]})

    def GET(self):
        username = self.req.params['username']
        pw = self.req.params['password']
        if auth.UserPermissions(self.datasvc.usersvc, None).validate_pw(username, pw):
            tokens = self.datasvc.usersvc.GetUserTokens(username)
            if len(tokens) > 0:
                return self.status_ok({"username": username, "token": tokens})
            else:
                return self.Error(400, "no token found for '{}'".format(username))
        else:
            return self.Error(403, "incorrect password")

    def DELETE(self):
        token = self.req.params['token']
        if token in self.datasvc.usersvc.GetAllTokens():
            username = self.datasvc.usersvc.GetUserFromToken(token)
            self.datasvc.usersvc.DeleteToken(token)
            return self.status_ok({"token_deleted": {"username": username, "token": token}})
        else:
            return self.Error(400, "unknown token")

class TokenView(GenericView):
    def __init__(self, context, request):
        #permissionless b/c the token is the secret. no need to supply token in URL and auth_token param
        GenericView.__init__(self, context, request, permissionless=True)

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
        try:
            mobj = models.__dict__[cname](context.doc)
        except elita_exceptions.SaltServerNotAccessible:
            return {
                'server': context.doc['name'],
                'error': "Server object not accessible via salt"
            }

    logger.debug("Model class: {}".format(cname))

    view_class = globals()[cname + "View"]

    return view_class(mobj, request).__call__()

class RootView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, permissionless=True)

    def GET(self):
        return About(self.req)

    def POST(self):
        return self.GET()
    def PUT(self):
        return self.GET()
    def DELETE(self):
        return self.GET()

import pkg_resources
@view_config(name="about", renderer='json')
def About(request):
    apps = request.datasvc.appsvc.GetApplications()
    return {
        'about': {
            'name': 'elita',
            'version': pkg_resources.require("elita")[0].version,
            'tagline': "You Know, for DevOps",
            'hostname': socket.getfqdn()
        },
        'stats': {
            'applications': len(apps),
            'servers': len(request.datasvc.serversvc.GetServers()),
            'builds': {a: len(request.datasvc.buildsvc.GetBuilds(a)) for a in apps},
            'gitrepos': {a: len(request.datasvc.gitsvc.GetGitRepos(a)) for a in apps},
            'gitdeploys': {a: len(request.datasvc.gitsvc.GetGitDeploys(a)) for a in apps},
            'users': len(request.datasvc.usersvc.GetUsers())
        }
    }




