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
import os

from elita.actions import action
import models
import builds
import auth
import servers
import elita.deployment.gitservice
import elita_exceptions
import elita.deployment.deploy
import elita.util

#logging.basicConfig(level=logging.DEBUG)
#logger = logging.getLogger()
#lh = logging.StreamHandler(sys.stdout)
#lh.setLevel(logging.DEBUG)
#logging.addHandler(lh)

AFFIRMATIVE_SYNONYMS = ("true", "True", "TRUE", "yup", "yep", "yut", "yes", "yea", "aye", "please", "si", "sim")


def validate_parameters(required_params=None, optional_params=None, json_body=None):
    '''
    Decorator that validates endpoint parameters and validates/deserializes JSON body
    '''
    assert elita.util.type_check.is_optional_seq(required_params)
    assert elita.util.type_check.is_optional_seq(optional_params)
    assert elita.util.type_check.is_optional_dict(json_body)

    def method_decorator(func):
        def wrapped_method(self):
            assert hasattr(self, 'req')

            missing_required_arg = None
            bad_json_body_msg = None

            def error_response():
                if missing_required_arg:
                    return self.Error(400, 'missing required argument: {}'.format(missing_required_arg))
                elif bad_json_body_msg:
                    return self.Error(400, 'bad JSON body: {}'.format(bad_json_body_msg))
                else:
                    return self.Error(400, 'bad request')

            if required_params:
                for r in required_params:
                    if r not in self.req.params:
                        missing_required_arg = r
                        return error_response()

            if isinstance(json_body, dict):
                try:
                    self.body = self.req.json_body
                except:
                    bad_json_body_msg = "problem deserializing (invalid JSON?)"
                    return error_response()
                for k in json_body:
                    if k not in self.body:
                        bad_json_body_msg = "missing key: {}".format(k)
                        return error_response()
                    if not isinstance(self.body[k], json_body[k]):
                        bad_json_body_msg = "invalid type for key {}: should be {} but is {}"\
                            .format(k, json_body[k].__class__.__name__, self.body[k].__class__.__name__)
                        return error_response()

            return func(self)

        return wrapped_method
    return method_decorator


class GenericView:
    #__metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, context, request, app_name="_global", permissionless=False, allow_pw_auth=False, is_action=False):
        self.required_params = {"GET": [], "PUT": [], "POST": [], "DELETE": []}  # { reqverb: [ params ] }
        logging.debug("{}: {} ; {}".format(self.__class__.__name__, context.__class__.__name__, request.subpath))
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

    def sanitize_doc_created_datetime(self, doc):
        '''
        created_datetime field in doc (as supplied by DataService) is a Python datetime object and is not serializable
        to JSON. If field exists on doc, convert to string in ISO format
        '''
        assert doc
        assert elita.util.type_check.is_dictlike(doc)
        if 'created_datetime' in doc:
            doc['created_datetime'] = doc['created_datetime'].isoformat(' ')
        return doc

    def run_async(self, name, job_type, data, callable, args):
        jid = action.run_async(self.datasvc, name, job_type, data, callable, args)
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

    #for verifying user-supplied parameters
    def check_against_existing(self, existing, submitted):
        return set(submitted).issubset(set(existing))

    def get_unknown(self, existing, submitted):
        return list(set(submitted) - set(existing))

    def check_patch_keys(self):
        '''
        Verify that the keys in the provided JSON body are a strict subset of the keys in the context object.
        For PATCH calls, we want to make sure that the user is only trying to modify keys that actually exist in the
        data model. PATCH should only ever be called on object endpoints (not containers) so the context object will be
        the corresponding data model object.
        '''
        assert hasattr(self.context, 'get_doc')
        assert self.body
        assert elita.util.type_check.is_dictlike(self.body)
        context_doc = self.context.get_doc()
        #don't let user change any part of composite key for the object
        for n in ('name', 'app_name', 'build_name', 'application', 'username'):
            if n in context_doc and n in self.body:
                return False, self.Error(400, "cannot change key value: {}".format(n))
        if not set(context_doc.keys()).issuperset(set(self.body.keys())):
            return False, self.Error(400, "unknown keys: {}".format(list(set(self.body.keys()) - set(context_doc.keys()))))
        return True, None

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
        elif self.req.method == 'PATCH' and not self.is_action:
            if 'write' in self.permissions:
                return self.PATCH()
        elif self.req.method == 'DELETE' and not self.is_action:
            if 'write' in self.permissions:
                return self.DELETE()
        else:
            bad_verb = True
        if bad_verb:
            return self.UNKNOWN_VERB()
        return self.UNAUTHORIZED()

    def check_params(self):
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
        if self.allow_pw_auth:
            if 'auth_token' not in self.req.params and 'Auth-Token' not in self.req.headers:
                # view sub-class responsible for verifying pw
                self.permissions = "read;write" if "password" in self.req.params else ""
                return
            elif "password" in self.req.params:  # both pw and auth token provided, fail the request
                self.permissions = ""
                return
        if 'auth_token' in self.req.params or 'Auth-Token' in self.req.headers:
            if 'auth_token' in self.req.params and 'Auth-Token' in self.req.headers:
                #if both are specified on one request it's an error condition
                token = ''
            else:
                submitted_tokens = self.req.params.getall('auth_token') if 'auth_token' in self.req.params else \
                    [self.req.headers['Auth-Token']]
                if len(submitted_tokens) != 1:  # multiple auth tokens are an error condition
                    token = ''
                else:
                    token = submitted_tokens[0]
            if self.is_action and self.req.method == 'POST':
                self.permissions = auth.UserPermissions(self.datasvc.usersvc, token).get_action_permissions(app_name,
                                                                                      self.context.action_name)
            else:
                self.permissions = auth.UserPermissions(self.datasvc.usersvc, token).get_app_permissions(app_name)
        else:
            self.permissions = ""

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
        logging.debug("REQUEST: url: {}".format(request.url))
        logging.debug("REQUEST: context: {}".format(context.__class__.__name__))
        logging.debug("REQUEST: method: {}".format(request.method))
        logging.debug("REQUEST: params: {}".format(request.params))

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
    logging.exception("")
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

    def validate_app_name(self, name):
        return name in self.datasvc.appsvc.GetApplications()

    @validate_parameters(required_params=["app_name"])
    def PUT(self):
        app_name = self.req.params["app_name"]
        self.datasvc.appsvc.NewApplication(app_name)
        return self.return_action_status({"new_application": {"name": app_name}})

    @validate_parameters(required_params=["app_name"])
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

    def GET(self):
        return {
            "application": self.context.app_name,
            "created": self.get_created_datetime_text(),
            self.context.app_name: self.datasvc.GetAppKeys(self.context.app_name)
            #"census": self.datasvc.appsvc.GetApplicationCensus(self.context.app_name)
        }

    def DELETE(self):
        self.datasvc.appsvc.DeleteApplication(self.context.app_name)
        return self.return_action_status({"delete_application": self.context.app_name})

    @validate_parameters(json_body={})
    def PATCH(self):
        ok, err = self.check_patch_keys()
        if not ok:
            return err
        self.datasvc.appsvc.UpdateApplication(self.context.app_name, self.body)
        return {
            'modified_application': self.sanitize_doc_created_datetime(self.datasvc.appsvc.GetApplication(self.context.app_name))
        }

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

    #cannot use decorator here since required parameters are dynamic
    def POST(self):
        return self.execute()

class BuildContainerView(GenericView):
    def __init__(self, context, request):
        self.app_name = context.parent
        GenericView.__init__(self, context, request, app_name=self.app_name)

    def validate_build_name(self, build_name):
        return build_name in self.datasvc.buildsvc.GetBuilds(self.app_name)

    def GET(self):
        return {"application": self.app_name,
                "builds": self.datasvc.buildsvc.GetBuilds(self.app_name)}

    @validate_parameters(required_params=["build_name"])
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

    @validate_parameters(required_params=["build_name"])
    def POST(self):
        build_name = self.req.params["build_name"]
        ok, err = self.validate_build_name(build_name)
        if not ok:
            return err
        return BuildView(self.context[build_name], self.req).POST()

    @validate_parameters(required_params=["build_name"])
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
        self.build_name = None

    def run_build_storage(self, func, arg):
        base_args = {
            'app': self.app_name,
            'build': self.build_name,
            'file_type': self.file_type,
            'package_map': self.package_map
        }
        args = dict(base_args.items() + arg.items())
        msg = self.run_async('store_build', 'async', args, func, args)
        return self.return_action_status({
            "build_stored": {
                "application": self.app_name,
                "build_name": self.build_name,
                "message": msg
            }
        })

    def run_build_storage_direct(self, tempfile):
        return self.run_build_storage(builds.store_uploaded_build, {'temp_file': tempfile})

    def run_build_storage_indirect(self, uri, verify):
        return self.run_build_storage(builds.store_indirect_build, {'uri': uri, 'verify': verify})

    def direct_upload(self):
        logging.debug("BuildView: direct_upload")
        if 'build' in self.req.POST:
            fname = self.req.POST['build'].filename
            logging.debug("BuildView: PUT: filename: {}".format(fname))
            fd, temp_file = tempfile.mkstemp()
            os.close(fd)
            with open(temp_file, 'wb') as f:
                f.write(self.req.POST['build'].file.read(-1))
            return self.run_build_storage_direct(temp_file)
        else:
            return self.Error(400, "build data not found in POST body")

    def indirect_upload(self):
        verify = self.req.params.getone('verify') in AFFIRMATIVE_SYNONYMS if 'verify' in self.req.params else False
        return self.run_build_storage_indirect(self.req.params['indirect_url'], verify)

    @validate_parameters(required_params=['file_type'], optional_params=['indirect_url', 'package_map'])
    def POST(self):
        self.build_name = self.context.build_name
        if self.req.params["file_type"] not in models.SupportedFileType.types:
            return self.Error(400, "file type not supported")
        self.file_type = self.req.params["file_type"]
        self.package_map = self.req.params['package_map'] if 'package_map' in self.req.params else None
        if self.package_map:
            if self.package_map not in self.datasvc.pmsvc.GetPackageMaps(self.app_name):
                return self.Error(400, "unknown package_map: {}".format(self.package_map))
            self.package_map = self.datasvc.pmsvc.GetPackageMap(self.app_name, self.package_map)['packages']

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

    @validate_parameters(json_body={})
    def PATCH(self):
        ok, err = self.check_patch_keys()
        if not ok:
            return err
        self.datasvc.buildsvc.UpdateBuild(self.context.app_name, self.context.build_name, self.body)
        return {
            'modifed_build': self.sanitize_doc_created_datetime(self.datasvc.buildsvc.GetBuild(self.context.app_name, self.context.build_name))
        }

    def DELETE(self):
        self.datasvc.buildsvc.DeleteBuild(self.context.app_name, self.context.build_name)
        return self.return_action_status({"delete_build": {"application": self.context.app_name,
                                                           "build_name": self.context.build_name}})


class ServerContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)

    def GET(self):
        return {
            'servers': self.datasvc.serversvc.GetServers()
        }

    @validate_parameters(required_params=['name', 'environment', 'existing'])
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
            job_data = {
                'server': name,
                'environment': environment,
                'existing': existing
            }
            msg = self.run_async("setup_new_server", "async", job_data, servers.setup_new_server, {'name': name})
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

    @validate_parameters(required_params=['name'])
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

    def GET(self):
        return {
            'server_name': self.context.name,
            'server_type': self.context.server_type,
            'status': self.context.status,
            'created_datetime': self.get_created_datetime_text(),
            'environment': self.context.environment,
            'attributes': self.context.attributes,
            'gitdeploys': self.datasvc.serversvc.GetGitDeploys(self.context.name)
        }

    @validate_parameters(json_body={})
    def PATCH(self):
        ok, err = self.check_patch_keys()
        if not ok:
            return err
        self.datasvc.serversvc.UpdateServer(self.context.name, self.body)
        return {
            'modified_server': self.sanitize_doc_created_datetime(self.datasvc.serversvc.GetServer(self.context.name))
        }

    def DELETE(self):
        self.datasvc.serversvc.DeleteServer(self.context.name)
        return self.status_ok({
            "server_deleted": {
                "server_name": self.context.name
            }
        })

class EnvironmentView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)

    def GET(self):
        return {
            'environments': self.datasvc.serversvc.GetEnvironments()
        }

class DeploymentContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.parent)

    def GET(self):
        return {
            'application': self.context.parent,
            'deployments': self.datasvc.deploysvc.GetDeployments(self.context.parent, sort="desc",
                                                                 with_details=True)
        }

    @validate_parameters(required_params=['build_name'])
    def POST(self):
        # yeah so this is a big ugly method...
        # we support two different 'styles' of deployment (manual/group) so this has to handle both and do all possible
        # input validation before returning. Prob should consider breaking this logic out into two separate endpoints.
        app = self.context.parent
        build_name = self.req.params['build_name']
        if build_name not in self.datasvc.buildsvc.GetBuilds(app):
            return self.Error(400, "unknown build '{}'".format(build_name))
        build_doc = self.datasvc.buildsvc.GetBuild(app, build_name)
        build_obj = models.Build(build_doc)
        if not build_obj.stored:
            return self.Error(400, "no stored data for build: {} (stored == false)".format(build_name))
        try:
            body = self.req.json_body
        except:
            return self.Error(400, "invalid target object (problem deserializing, bad JSON?)")

        target = {
            "servers": list(),
            "gitdeploys": list()
        }
        integer_params = {  # defaults
            "rolling_divisor": 2,
            "rolling_pause": 0,
            "ordered_pause": 0
        }
        for p in integer_params.keys():
            try:
                if p in self.req.params:
                    integer_params[p] = int(self.req.params[p])
            except ValueError:
                return self.Error(400, "invalid {}".format(p))
            if integer_params[p] < (1 if p == "rolling_divisor" else 0):
                return self.Error(400, "invalid {}: {}".format(p, integer_params[p]))

        rolling_divisor = integer_params['rolling_divisor']
        rolling_pause = integer_params['rolling_pause']
        ordered_pause = integer_params['ordered_pause']

        if "environments" in body and "groups" in body:

            for c in ('environments', 'groups'):
                if not isinstance(body[c], list):
                    return self.Error(400, "{} must be a list".format(c))

            envs = self.datasvc.serversvc.GetEnvironments()
            if not self.check_against_existing(envs.keys(), body['environments']):
                return self.Error(400, "unknown environments: {}".format(self.get_unknown(envs.keys(), body['environments'])))

            existing_groups = self.datasvc.groupsvc.GetGroups(app)
            if not self.check_against_existing(existing_groups, body['groups']):
                return self.Error(400, "unknown groups: {}".format(self.get_unknown(existing_groups, body['groups'])))

            #flat list of all servers in environments
            servers_in_environments = set([s for s in [envs[e] for e in envs] for s in s])
            servers_in_groups = set([s for s in [self.datasvc.groupsvc.GetGroupServers(app, g) for g in body['groups']]
                                 for s in s])
            target['servers'] = list(servers_in_environments.intersection(servers_in_groups))
            target['gitdeploys'] = set()
            for group in body['groups']:
                group = self.datasvc.groupsvc.GetGroup(app, group)
                assert 'gitdeploys' in group
                assert isinstance(group['gitdeploys'], list)
                assert len(group['gitdeploys']) > 0
                if isinstance(group['gitdeploys'][0], list):
                    target['gitdeploys'].update([gd for sublist in group['gitdeploys'] for gd in sublist])
                else:
                    target['gitdeploys'].update(group['gitdeploys'])
            target['gitdeploys'] = list(target['gitdeploys'])

            logging.debug("DeploymentContainerView: calculated target: {}".format(target))

            for k in target:
                if target[k] < 1:
                    return self.Error(400, "no matching {} for environments ({}) and groups ({})"
                                      .format(k, body['environments'], body['groups']))

        if "servers" in body and "gitdeploys" in body:

            for c in ('servers', 'gitdeploys'):
                if not isinstance(body[c], list):
                    return self.Error(400, "{} must be a list".format(c))

            existing_servers = self.datasvc.serversvc.GetServers()
            if not self.check_against_existing(existing_servers, body['servers']):
                return self.Error(400, "unknown servers: {}".format(self.get_unknown(existing_servers, body['servers'])))

            existing_gitdeploys = self.datasvc.gitsvc.GetGitDeploys(app)
            if not self.check_against_existing(existing_gitdeploys, body['gitdeploys']):
                return self.Error(400, "unknown gitdeploys: {}".format(self.get_unknown(existing_gitdeploys,
                                                                                   body['gitdeploys'])))
            for s in body['servers']:
                target['servers'].append(s)
            for gd in body['gitdeploys']:
                target['gitdeploys'].append(gd)

            #verify that all servers have the requested gitdeploys initialized on them
            uninit_gd = dict()
            for gd in target['gitdeploys']:
                gddoc = self.datasvc.gitsvc.GetGitDeploy(app, gd)
                init_servers = set(tuple(gddoc['servers']))
                req_servers = set(tuple(target['servers']))
                if not init_servers.issuperset(req_servers):
                    uninit_gd[gd] = list(req_servers - init_servers)
            if len(uninit_gd) > 0:
                return self.Error(400, {"message": "gitdeploy not initialized on servers", "servers": uninit_gd})

        if len(target['servers']) == 0:
            return self.Error(400, "no servers specified for deployment (are you sure the gitdeploys are initialized?)")

        # do a final check to make sure all required packages are present in the build
        gddocs = [self.datasvc.gitsvc.GetGitDeploy(app, gd) for gd in target['gitdeploys']]
        for gd in gddocs:
            if gd['package'] not in build_obj.packages:
                return self.Error(400, "package {} not found in build {} (required by gitdeploy {})"
                                  .format(gd['package'], build_name, gd['name']))

        environments = body['environments'] if 'environments' in body else None
        groups = body['groups'] if 'groups' in body else None
        dpo = self.datasvc.deploysvc.NewDeployment(app, build_name, environments, groups, target['servers'],
                                                   target['gitdeploys'], integer_params)
        d_id = dpo['NewDeployment']['id']
        target['environments'] = environments if isinstance(environments, list) else None
        target['groups'] = groups if isinstance(groups, list) else None
        args = {
            'application': app,
            'build_name': build_name,
            'target': target,
            'rolling_divisor': rolling_divisor,
            'rolling_pause': rolling_pause,
            'ordered_pause': ordered_pause,
            'deployment_id': d_id
        }
        msg = self.run_async('deploy_{}_{}'.format(app,  build_name), "deployment", args,
                             elita.deployment.deploy.run_deploy, args)
        self.datasvc.deploysvc.UpdateDeployment(app, d_id, {'status': 'running', 'job_id': msg['job_id']})
        return self.status_ok({
            'deployment': {
                'deployment_id': dpo['NewDeployment']['id'],
                'application': app,
                'build': build_name,
                'environments': environments,
                'groups': groups,
                'rolling_divisor': rolling_divisor,
                'rolling_pause': rolling_pause,
                'servers': target['servers'],
                'gitdeploys': target['gitdeploys'],
                'message': msg
            }
        })


class DeploymentView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.application)

    def GET(self):
        return {
            'deployment': {
                'id': self.context.name,
                'job_id': self.context.job_id,
                'created_datetime': self.get_created_datetime_text(),
                'application': self.context.application,
                'deployment': self.context.deploy if hasattr(self.context, 'deploy') else None,
                'environments': self.context.environments if hasattr(self.context, 'environments') else None,
                'groups': self.context.groups if hasattr(self.context, 'groups') else None,
                'build': self.context.build_name,
                'servers': self.context.servers if hasattr(self.context, 'servers') else None,
                'commits': self.context.commits if hasattr(self.context, 'commits') else None,
                'gitdeploys': self.context.gitdeploys if hasattr(self.context, 'gitdeploys') else None,
                'status': self.context.status,
                'progress': self.context.progress
            }
        }


class KeyPairContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name='_global')

    def GET(self):
        return {
            'keypairs': self.datasvc.keysvc.GetKeyPairs()
        }

    def new_keypair(self, name, private_key, public_key, attributes, key_type):
        ret = self.datasvc.keysvc.NewKeyPair(name, attributes, key_type, private_key, public_key)
        if ret['NewKeyPair']['status'] == 'ok':
            return self.status_ok({'new_keypair': {'name': name, 'key_type': key_type}})
        else:
            return self.Error(500, ret)

    @validate_parameters(required_params=['name', 'key_type', 'from'])
    def PUT(self):
        name = self.req.params['name']
        key_type = self.req.params['key_type']
        if self.req.params['from'] not in ('json', 'files'):
            return self.Error(400, "invalid 'from' type: {}; must be 'json' or 'files'".format(self.req.params['from']))
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
        return self.new_keypair(name, private_key, public_key, attributes, key_type)

    @validate_parameters(required_params=['name', 'key_type', 'from'])
    def POST(self):
        name = self.req.params['name']
        key_type = self.req.params['key_type']
        attributes = dict()
        logging.debug("POST keys: {}".format(self.req.POST.keys()))
        for kt in ("private_key", "public_key"):
            if kt not in self.req.POST:
                return self.Error(400, "{} not found in POST data".format(kt))
            pr_file = self.req.POST['private_key'].file
            pr_file.seek(0)
            pk_file = self.req.POST['public_key'].file
            pk_file.seek(0)
            private_key = pr_file.read(-1)
            public_key = pk_file.read(-1)

        return self.new_keypair(name, private_key, public_key, attributes, key_type)

    @validate_parameters(required_params=['name'])
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

    @validate_parameters(json_body={})
    def PATCH(self):
        ok, err = self.check_patch_keys()
        if not ok:
            return err
        self.datasvc.keysvc.UpdateKeyPair(self.context.name, self.body)
        return {
            'modifed_keypair': self.sanitize_doc_created_datetime(self.datasvc.keysvc.GetKeyPair(self.context.name))
        }

    def DELETE(self):
        self.datasvc.keysvc.DeleteKeyPair(self.context.name)
        return self.status_ok({'delete_keypair': {'name': self.context.name}})


class GitProviderContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)

    def GET(self):
        return {
            'gitproviders': self.datasvc.gitsvc.GetGitProviders()
        }

    @validate_parameters(required_params=['name'])
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

    @validate_parameters(required_params=['name'])
    def POST(self):
        return self.PUT()

    @validate_parameters(required_params=['name'])
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

    @validate_parameters(json_body={})
    def PATCH(self):
        ok, err = self.check_patch_keys()
        if not ok:
            return err
        self.datasvc.gitsvc.UpdateGitProvider(self.context.name)
        return {
            'modifed_gitprovider': self.sanitize_doc_created_datetime(self.datasvc.gitsvc.GetGitProvider(self.context.name))
        }

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

    def GET(self):
        return {
            'application': self.context.parent,
            'gitrepos': self.datasvc.gitsvc.GetGitRepos(self.context.parent)
        }

    @validate_parameters(required_params=['name', 'existing', 'gitprovider', 'keypair'])
    def PUT(self):
        existing = self.req.params['existing'] in AFFIRMATIVE_SYNONYMS
        gitprovider = self.req.params['gitprovider']
        keypair = self.req.params['keypair']
        name = self.req.params['name']

        if not existing:
            uri = None
            kp = self.datasvc.keysvc.GetKeyPair(keypair)
            if not kp:
                return self.Error(400, "unknown keypair")
            gp_doc = self.datasvc.gitsvc.GetGitProvider(gitprovider)
            if not gp_doc:
                return self.Error(400, "unkown gitprovider")
            logging.debug("GitRepoContainerView: gp_doc: {}".format(gp_doc))
            repo_callable = elita.deployment.gitservice.create_repo_callable_from_type(gp_doc['type'])
            if not repo_callable:
                return self.Error(400, "gitprovider type not supported ({})".format(gp_doc['type']))
            args = {
                'gitprovider': gp_doc,
                'name': name,
                'application': self.context.parent,
                'keypair': kp
            }
            job_data = {
                'gitprovider': gp_doc['name'],
                'name': name,
                'application': self.context.parent,
                'keypair': kp['name']
            }
            msg = self.run_async("create_repository", "async", job_data, repo_callable, args)
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
            args = {
                'gitrepo': gitrepo
            }
            msg = self.run_async("create_extant_gitrepo", "async", {'gitrepo': gitrepo['name']},
                                 elita.deployment.gitservice.setup_local_gitrepo_dir, args)
        return self.status_ok({
            'new_gitrepo': ret,
            'message': msg
        })

    @validate_parameters(required_params=['name'])
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

    def GET(self):
        gitrepo = self.datasvc.gitsvc.GetGitRepo(self.context.application, self.context.name)
        assert gitrepo and 'gitprovider' in gitrepo and 'auth' in gitrepo['gitprovider']
        #re-reference embedded fields
        gitrepo['gitprovider'] = gitrepo['gitprovider']['name']
        gitrepo['keypair'] = gitrepo['keypair']['name']
        return {
            'gitrepo': gitrepo
        }

    @validate_parameters(json_body={})
    def PATCH(self):
        ok, err = self.check_patch_keys()
        if not ok:
            return err
        self.datasvc.gitsvc.UpdateGitRepo(self.context.application, self.context.name, self.body)
        return {
            'modified_gitrepo': self.sanitize_doc_created_datetime(self.datasvc.gitsvc.GetGitRepo(self.context.application, self.context.name))
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
            args = {
                'gitprovider': gp_doc,
                'name': self.context.name
            }
            job_data = {
                'gitprovider': gp_doc['name'],
                'name': self.context.name
            }
            msg = self.run_async("delete_repository", "async", job_data, del_callable, args)
            resp['message'] = {'delete_repository': msg}
        return self.status_ok(resp)


class GitDeployContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.parent)

    def GET(self):
        return {
            'application': self.context.parent,
            'gitdeploys': self.datasvc.gitsvc.GetGitDeploys(self.context.parent)
        }

    @validate_parameters(required_params=['name'])
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
        if location['gitrepo'] not in self.datasvc.gitsvc.GetGitRepos(app):
            return self.Error(400, "unknown gitrepo: {}".format(location['gitrepo']))
        res = self.datasvc.gitsvc.NewGitDeploy(name, app, package, options, actions, location, attribs)
        if 'error' in res:
            return self.Error(500, {"NewGitDeploy": res})
        gd = self.datasvc.gitsvc.GetGitDeploy(app, name)
        args = {'gitdeploy': gd}
        msg = self.run_async("create_gitdeploy", "async", {'gitdeploy': gd['name']},
                             elita.deployment.gitservice.create_gitdeploy, args)
        return self.status_ok({'create_gitdeploy': {'name': name, 'message': msg}})


class GitDeployView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.application)

    def GET(self):
        gddoc = self.datasvc.gitsvc.GetGitDeploy(self.context.application, self.context.name)
        #re-reference embedded
        gddoc['location']['gitrepo'] = gddoc['location']['gitrepo']['name']
        return {k: gddoc[k] for k in gddoc if k[0] != '_'}

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

    def initialize(self, body):
        ok, err = self.check_servers_list(body)
        if not ok:
            return err
        #we need to get the fully dereferenced doc
        gddoc = self.datasvc.gitsvc.GetGitDeploy(self.context.application, self.context.name)
        args = {
            'gitdeploy': gddoc,
            'server_list': self.servers
        }
        job_data = {
            'gitdeploy': gddoc['name'],
            'application': self.context.application,
            'servers': self.servers
        }
        msg = self.run_async('initialize_gitdeploy_servers', "async", job_data,
                             elita.deployment.gitservice.initialize_gitdeploy, args)
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
        args = {
            'gitdeploy': gddoc, 'server_list': self.servers
        }
        job_data = {
            'gitdeploy': gddoc['name'],
            'application': self.context.application,
            'servers': self.servers
        }
        msg = self.run_async('deinitialize_gitdeploy_servers', "async", job_data,
                             elita.deployment.gitservice.deinitialize_gitdeploy, args)
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
            return self.Error(400, "neither init or deinit requested")

    @validate_parameters(json_body={})
    def PATCH(self):
        ok, err = self.check_patch_keys()
        if not ok:
            return err
        self.datasvc.gitsvc.UpdateGitDeploy(self.context.application, self.context.name, self.body)
        gd = self.datasvc.gitsvc.GetGitDeploy(self.context.application, self.context.name)
        return {
            'modified_gitdeploy': self.sanitize_doc_created_datetime(gd),
            'message': self.run_async("create_gitdeploy", "async", {'gitdeploy': gd['name']},
                             elita.deployment.gitservice.create_gitdeploy, {'gitdeploy': gd})
        }

    def DELETE(self):
        gddoc = self.datasvc.gitsvc.GetGitDeploy(self.context.application, self.context.name)
        args = {'gitdeploy': gddoc}
        groups_deleted = False
        delete_groups = list()
        if "delete_groups" in self.req.params and self.req.params['delete_groups'] in AFFIRMATIVE_SYNONYMS:
            groups = self.datasvc.appsvc.GetGroups(self.context.application)
            for g in groups:
                group = self.datasvc.appsvc.GetGroup(self.context.application, g)
                if self.context.name in group['gitdeploys']:
                    delete_groups.append(g)
            for g in delete_groups:
                logging.debug("deleting group: {} (application: {})".format(g, self.context.application))
                self.datasvc.appsvc.DeleteGroup(self.context.application, g)
            groups_deleted = True

        msg = self.run_async('remove_deinitialize_gitdeploy', "async", {'gitdeploy': gddoc['name']},
                             elita.deployment.gitservice.remove_and_deinitialize_gitdeploy, args)
        status_msg = {
            'delete_deinitialize_gitdeploy': {
                'application': gddoc['application'],
                'name': gddoc['name'],
                'servers': gddoc['servers'] if 'servers' in gddoc else list(),
                'msg': msg
            }
        }
        if groups_deleted:
            status_msg['delete_deinitialize_gitdeploy']['groups_deleted'] = delete_groups
        return self.status_ok(status_msg)


class GlobalContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, permissionless=True)

    def GET(self):
        return {"global": self.datasvc.GetGlobalKeys()}


class GroupContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.parent)

    def GET(self):
        return {
            'application': self.context.parent,
            'groups': self.datasvc.groupsvc.GetGroups(self.context.parent)
        }

    @validate_parameters(required_params=["name", "rolling_deploy"])
    def PUT(self):
        name = self.req.params['name']
        rolling_deploy = self.req.params['rolling_deploy'] in AFFIRMATIVE_SYNONYMS
        try:
            gitdeploys = self.req.json_body
        except:
            return self.Error(400, "invalid gitdeploys object (problem deserializing, bad JSON?)")
        if "gitdeploys" not in gitdeploys.keys():
            return self.Error(400, "JSON missing key 'gitdeploys'")
        if not isinstance(gitdeploys['gitdeploys'], list):
            return self.Error(400, "gitdeploys must be list")
        description = gitdeploys['description'] if 'description' in gitdeploys else ""
        attributes = gitdeploys['attributes'] if 'attributes' in gitdeploys else dict()

        existing_gitdeploys = set(self.datasvc.gitsvc.GetGitDeploys(self.context.parent))
        submitted_gitdeploys = set([gd for sublist in gitdeploys['gitdeploys'] for gd in sublist]) \
            if isinstance(gitdeploys['gitdeploys'][0], list) else set(gitdeploys['gitdeploys'])
        if not existing_gitdeploys.issuperset(submitted_gitdeploys):
            return self.Error(400, "unknown gitdeploys: {}".format(list(submitted_gitdeploys - existing_gitdeploys)))

        self.datasvc.groupsvc.NewGroup(self.context.parent, name, gitdeploys['gitdeploys'], description=description,
                                       attributes=attributes, rolling_deploy=rolling_deploy)
        return self.status_ok({
            "New_Group": {
                "name": name,
                "description": description,
                "application": self.context.parent,
                "attributes": attributes,
                "rolling_deploy": rolling_deploy,
                "gitdeploys": gitdeploys['gitdeploys']
            }
        })

    @validate_parameters(required_params=["name"])
    def DELETE(self):
        name = self.req.params['name']
        if name not in self.datasvc.groupsvc.GetGroups(self.context.parent):
            return self.Error(400, "unknown group: {}".format(name))
        self.datasvc.groupsvc.DeleteGroup(self.context.parent, name)
        return self.status_ok({
            "Delete_Group": {
                "name": name,
                "application": self.context.parent
            }
        })

class GroupView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.application)

    def GET(self):
        environments = self.req.params['environments'].split(' ') \
            if ('environments' in self.req.params and len(self.req.params['environments']) > 0) else None
        if environments:
            existing_groups = self.datasvc.serversvc.GetEnvironments()
            if not self.check_against_existing(existing_groups, environments):
                return self.Error(400, "unknown environments: {}".format(self.get_unknown(existing_groups, environments)))
        return {
            'created': self.get_created_datetime_text(),
            'application': self.context.application,
            'description': self.context.description,
            'name': self.context.name,
            'attributes': self.context.attributes,
            'rolling_deploy': self.context.rolling_deploy,
            'gitdeploys': self.context.gitdeploys,
            'servers': self.datasvc.groupsvc.GetGroupServers(self.context.application, self.context.name,
                                                             environments=environments),
            'environments': environments if environments else "(any)"
        }

    @validate_parameters(json_body={})
    def PATCH(self):
        ok, err = self.check_patch_keys()
        if not ok:
            return err
        self.datasvc.groupsvc.UpdateGroup(self.context.application, self.context.name, self.body)
        return {
            'modified_group': self.sanitize_doc_created_datetime(self.datasvc.groupsvc.GetGroup(self.context.application, self.context.name))
        }

    def DELETE(self):
        self.datasvc.groupsvc.DeleteGroup(self.context.application, self.context.name)
        return self.status_ok({
            "Delete_Group": {
                "name": self.context.name,
                "application": self.context.application
            }
        })


class PackageMapContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.parent)

    def GET(self):
        return {
            'application': self.context.parent,
            'packagemaps': self.datasvc.pmsvc.GetPackageMaps(self.context.parent)
        }

    @validate_parameters(required_params=['name'], json_body={'packages': dict})
    def PUT(self):
        attributes = self.body['attributes'] if 'attributes' in self.body else None
        if not self.body['packages']:
            return self.Error(400, 'invalid packages object: appears to be empty')
        for pkg in self.body['packages']:
            package = self.body['packages'][pkg]
            supported_keys = {'patterns', 'prefix', 'remove_prefix'}
            if not package:
                return self.Error(400, 'invalid packages object: empty')
            if not set(package.keys()).issubset(supported_keys):
                return self.Error(400, "unknown keys in package {}: {}"
                                  .format(pkg, list(supported_keys - set(package.keys()))))
            if 'patterns' not in package:
                return self.Error(400, "{}: patterns missing".format(pkg))

            if 'prefix' in package:
                if not elita.util.type_check.is_string(package['prefix']):
                    return self.Error(400, '{}: prefix must be a string'.format(pkg))
                if not package['prefix']:
                    return self.Error(400, '{}: prefix appears is empty'.format(pkg))

            if 'remove_prefix' in package:
                if not elita.util.type_check.is_string(package['remove_prefix']):
                    return self.Error(400, '{}: remove_prefix must be a string'.format(pkg))
                if not package['remove_prefix']:
                    return self.Error(400, '{}: remove_prefix appears is empty'.format(pkg))

            if not isinstance(package['patterns'], list):
                return self.Error(400, '{}: patterns must be a list'.format(pkg))

            for i, p in enumerate(package['patterns']):
                if not elita.util.type_check.is_string(p):
                    return self.Error(400, '{}: patterns index {}: pattern must be a string'.format(pkg, i))
                if not p:
                    return self.Error(400, '{}: patterns index {}: pattern is empty'.format(pkg, i))

        self.datasvc.pmsvc.NewPackageMap(self.context.parent, self.req.params['name'], self.body['packages'], attributes)
        return self.status_ok({
            "New_PackageMap": {
                "name": self.req.params['name'],
                "application": self.context.parent,
                "attributes": attributes,
                "packages": self.body['packages']
            }
        })

    @validate_parameters(required_params=['name'])
    def DELETE(self):
        name = self.req.params['name']
        if name not in self.datasvc.pmsvc.GetPackageMaps(self.context.parent):
            return self.Error(400, "unknown package map: {}".format(name))
        self.datasvc.pmsvc.DeletePackageMap(self.context.parent, name)
        return self.status_ok({
            "Delete_PackageMap": {
                "name": self.req.params['name'],
                "application": self.context.parent
            }
        })

class PackageMapView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, app_name=context.application)

    def GET(self):
         return {
            'created': self.get_created_datetime_text(),
            'application': self.context.application,
            'name': self.context.name,
            'attributes': self.context.attributes,
            'packages': self.context.packages
         }

    @validate_parameters(json_body={})
    def PATCH(self):
        ok, err = self.check_patch_keys()
        if not ok:
            return err
        self.datasvc.pmsvc.UpdatePackageMap(self.context.application, self.context.name, self.body)
        return {
            'modified_packagemap': self.sanitize_doc_created_datetime(self.datasvc.pmsvc.GetPackageMap(self.context.application, self.context.name))
        }

    def DELETE(self):
        self.datasvc.pmsvc.DeletePackageMap(self.context.application, self.context.name)
        return self.status_ok({
            "Delete_PackageMap": {
                "name": self.context.name,
                "application": self.context.application
            }
        })


class UserContainerView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request)

    @validate_parameters(required_params=["username", "password"])
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

    @validate_parameters(required_params=['username'])
    def DELETE(self):
        name = self.req.params['username']
        if name in self.datasvc.usersvc.GetUsers():
            self.datasvc.usersvc.DeleteUser(name)
            return self.status_ok({"user_deleted": {"username": name}})
        else:
            return self.Error(400, "unknown user")

class JobView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, permissionless=True)  # job_id is the secret

    def GET(self):
        ret = {
            'job_id': str(self.context.job_id),
            'name': self.context.name,
            'job_type': self.context.job_type,
            'data': self.context.data,
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

    @validate_parameters(required_params=['active'])
    def GET(self):
        active = self.req.params['active'] in AFFIRMATIVE_SYNONYMS
        return {"jobs": {"active": active, "job_ids": self.datasvc.jobsvc.GetJobs(active=active)}}


class UserView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, allow_pw_auth=True)  # allow both pw and auth_token auth

    def check_password(self):
        if 'password' in self.req.params:
            if not self.context.validate_password(self.req.params['password']):
                return False, self.Error(403, "incorrect password")
            else:
                return True, None
        elif ('auth_token' not in self.req.params) and ('Auth-Token' not in self.req.headers):
            return False, self.Error(403, "password or auth token required")
        else:
            if 'auth_token' in self.req.params and len(self.req.params.getall('auth_token')) > 1:  # multiple auth tokens
                return False, self.Error(403, "incorrect authentication")
            token = self.req.params.getall('auth_token')[0] if 'auth_token' in self.req.params else self.req.headers['Auth-Token']
            authsvc = auth.UserPermissions(self.datasvc.usersvc, token, datasvc=self.datasvc)
            allowed_apps = authsvc.get_allowed_apps()
            global_read = False
            for k in allowed_apps:
                if 'read' in k:
                    if '_global' in allowed_apps[k]:
                        global_read = True
            if authsvc.valid_token and (global_read or authsvc.username == self.context.username):
                return True, None
        logging.debug("valid_token: {}".format(authsvc.valid_token))
        logging.debug("usernames: {}, {}".format(authsvc.username, self.context.username))
        logging.debug("allowed_apps: {}".format(authsvc.get_allowed_apps()))
        return False, self.Error(403, "bad token")

    def GET(self):
        # another ugly. we want to support both password auth and valid tokens, but only tokens from the same user or
        #  with the '_global' permission.
        ok, err = self.check_password()
        if not ok:
            return err
        name = self.context.username
        if len(self.datasvc.usersvc.GetUserTokens(name)) == 0:
            self.datasvc.usersvc.NewToken(name)
        return {
            "user": {
                "username": name,
                "permissions": self.context.permissions,
                "attributes": self.context.attributes,
                "auth_token": self.datasvc.usersvc.GetUserTokens(name)
            }
        }

    @validate_parameters(json_body={})
    def PATCH(self):
        ok, err = self.check_password()
        if not ok:
            return err
        ok, err = self.check_patch_keys()
        if not ok:
            return err
        self.datasvc.usersvc.UpdateUser(self.context.username, self.body)
        return {
            'modified_user': self.sanitize_doc_created_datetime(self.datasvc.usersvc.GetUser(self.context.username))
        }


class UserPermissionsView(GenericView):
    def __init__(self, context, request):
        GenericView.__init__(self, context, request, allow_pw_auth=True)

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

    @validate_parameters(required_params=["username", "password"])
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

    @validate_parameters(required_params=["token"])
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


@view_config(name="", renderer='json')
def Action(context, request):
    '''
    Default unnamed 'root' view that gets called for every request that doesn't 404 during traversal
    '''
    logging.debug("REQUEST: url: {}".format(request.url))
    logging.debug("REQUEST: context: {}".format(context.__class__.__name__))
    logging.debug("REQUEST: method: {}".format(request.method))
    logging.debug("REQUEST: params: {}".format(request.params))

    pp = pprint.PrettyPrinter(indent=4)
    if context.__class__.__name__ == 'Action':
        logging.debug("REQUEST: action")
        mobj = context
        cname = "Action"
    else:
        logging.debug("REQUEST: context.doc: {}".format(pp.pformat(context.doc)))
        cname = context.doc['_class']
        try:
            mobj = models.__dict__[cname](context.doc)
        except elita_exceptions.SaltServerNotAccessible:
            return {
                'server': context.doc['name'],
                'error': "Server object not accessible via salt"
            }

    logging.debug("Model class: {}".format(cname))

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
    appstats = {
        a: {
            'builds': len(request.datasvc.buildsvc.GetBuilds(a)),
            'gitrepos': len(request.datasvc.gitsvc.GetGitRepos(a)),
            'gitdeploys': len(request.datasvc.gitsvc.GetGitDeploys(a))
        } for a in apps}
    return {
        'about': {
            'name': 'elita',
            'version': pkg_resources.require("elita")[0].version,
            'tagline': "You Know, for DevOps",
            'hostname': socket.getfqdn()
        },
        'stats': {
            'applications': appstats,
            'servers': len(request.datasvc.serversvc.GetServers()),
            'users': len(request.datasvc.usersvc.GetUsers())
        }
    }




