__author__ = 'bkeroack'

import logging
import os
import shutil
import bson
import datetime
import pytz
import copy
import sys
import jsonpatch

import elita.util
import elita.elita_exceptions
import models
from root_tree import RootTree
from mongo_service import MongoService
from elita.deployment.gitservice import EMBEDDED_YAML_DOT_REPLACEMENT
from elita.actions.action import ActionService
from elita.deployment import deploy, salt_control

class GenericChildDataService:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, mongo_service, root, settings, job_id=None):
        '''
        @type mongo_service: MongoService
        @type root: RootTree
        @type settings: pyramid.registry.Registry
        @type job_id: None | str
        '''
        assert isinstance(mongo_service, MongoService)
        assert isinstance(root, RootTree)
        assert elita.util.type_check.is_optional_str(job_id)
        self.mongo_service = mongo_service
        self.root = root
        self.settings = settings
        self.job_id = job_id

    def populate_dependencies(self, dependency_objs):
        '''
        Child dataservice classes may need to access methods of siblings. This allows parent dataservice to inject
        cross dependencies as needed without generating a big reference cycle.

        dependency_objs = { 'FooDataService': FooDataService }

        @type dependency_objs: dict
        '''
        assert elita.util.type_check.is_dictlike(dependency_objs)
        self.deps = dependency_objs

    def NewContainer(self, class_name, name, parent):
        '''
        Create new container object suitable for a root_tree reference
        '''
        assert class_name and name and parent
        assert elita.util.type_check.is_string(class_name)
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_string(parent)
        return self.mongo_service.create_new('containers', {'name': name, 'parent': parent}, class_name,
                                             {'name': name, 'parent': parent}, remove_existing=False)

    def UpdateObjectFromPatch(self, collection, keys, patch):
        '''
        Generic method to update an object (document) with a JSON Patch document
        '''
        assert collection and keys and patch
        assert elita.util.type_check.is_string(collection)
        assert elita.util.type_check.is_dictlike(keys)
        assert elita.util.type_check.is_seq(patch)

        assert all([len(str(op["path"]).split('/')) > 1 for op in patch])  # well-formed path for every op
        assert not any([str(op["path"]).split('/')[1][0] == '_' for op in patch])  # not trying to operate on internal fields

        original_doc = self.mongo_service.get(collection, keys)
        assert original_doc
        result = jsonpatch.apply_patch(original_doc, patch)
        self.mongo_service.save(collection, result)

    def UpdateObject(self, collection, keys, doc):
        '''
        Generic method to update a particular object (document) with the data in doc
        '''
        assert collection and keys and doc
        assert elita.util.type_check.is_string(collection)
        assert elita.util.type_check.is_dictlike(keys)
        assert elita.util.type_check.is_dictlike(doc)

        paths = elita.util.paths_from_nested_dict(doc)
        assert paths
        for path in paths:
            self.mongo_service.modify(collection, keys, path[:-1], path[-1])

    def AddThreadLocalRootTree(self, path):
        '''
        Add new node to thread-local root_tree (copy from mongo's root_tree)
        '''
        assert path
        assert elita.util.type_check.is_seq(path)
        root_tree = self.mongo_service.get('root_tree', {})
        assert root_tree
        reduce(lambda d, k: d[k], path[:-1], self.root)[path[-1]] = reduce(lambda d, k: d[k], path, root_tree)

    def RmThreadLocalRootTree(self, path):
        '''
        Remove deleted node from thread-local root_tree
        '''
        assert path
        assert elita.util.type_check.is_seq(path)
        node = reduce(lambda d, k: d[k], path[:-1], self.root)
        del node[path[-1]]


class BuildDataService(GenericChildDataService):

    def GetBuilds(self, app_name):
        '''
        Get all builds for application.

        When getting a list of all objects of a given type, the convention is to pull from in-memory root_tree instead
        of directly from mongo. This keeps it fast so we can do it frequently for things like parameter validation, etc
        '''
        assert app_name
        assert elita.util.type_check.is_string(app_name)
        assert app_name in self.root['app']
        return [build for build in self.root['app'][app_name]['builds'] if build[0] != '_']

    def NewBuild(self, app_name, build_name, attribs):
        '''
        Create new build document
        '''
        assert elita.util.type_check.is_string(app_name)
        assert elita.util.type_check.is_string(build_name)
        assert isinstance(attribs, dict)
        assert app_name and build_name

        app_doc = self.mongo_service.get('applications', {'app_name': app_name})
        assert app_doc

        buildobj = models.Build({
            'app_name': app_name,
            'build_name': build_name,
            'attributes': attribs
        })

        bid = self.mongo_service.create_new('builds', {'app_name': app_name, 'build_name': build_name}, 'Build',
                                            buildobj.get_doc())
        self.mongo_service.update_roottree(('app', app_name, 'builds', build_name), 'builds', bid)
        self.AddThreadLocalRootTree(('app', app_name, 'builds', build_name))
        return True

    def AddPackages(self, app, build, packages):
        '''
        Add new packages fields to existing build. Regenerate legacy 'files' field (which is a flat array of files
        associated with build
        '''

        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(build)
        assert isinstance(packages, dict)
        assert app in self.root['app']
        assert build in self.root['app'][app]['builds']

        keys = {'app_name': app, 'build_name': build}
        for p in packages:
            path = ('packages', p)
            self.mongo_service.modify('builds', keys, path, packages[p])

        build_doc = self.mongo_service.get('builds', keys)
        assert all([p in build_doc['packages'] for p in packages])

        #generate files from packages (avoid dupes)
        files = [{"file_type": packages[p]['file_type'], "path": packages[p]['filename']} for p in packages]
        self.mongo_service.modify('builds', keys, ('files',), files)

    def UpdateBuild(self, app, name, doc):
        '''
        Update build with doc (JSON Patch or keys to update).
        '''
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_dictlike(doc) or elita.util.type_check.is_seq(doc)
        assert app and name
        assert app in self.root['app']
        assert name in self.root['app'][app]['builds']

        if elita.util.type_check.is_dictlike(doc):
            self.UpdateObject('builds', {'app_name': app, 'build_name': name}, doc)
        else:
            try:
                self.UpdateObjectFromPatch('builds', {'app_name': app, 'build_name': name}, doc)
            except:
                return False
        return True

    def DeleteBuildStorage(self, app_name, build_name):
        '''
        Delete all stored files associated with build.
        '''
        assert elita.util.type_check.is_string(app_name)
        assert elita.util.type_check.is_string(build_name)
        assert app_name and build_name

        app_doc = self.mongo_service.get('applications', {'app_name': app_name})
        assert app_doc

        dir = self.settings['elita.builds.dir']
        path = "{root_dir}/{app}/{build}".format(root_dir=dir, app=app_name, build=build_name)
        logging.debug("DeleteBuildStorage: path: {}".format(path))
        if os.path.isdir(path):
            logging.debug("DeleteBuildStorage: remove_build: deleting")
            shutil.rmtree(path)

    def DeleteBuild(self, app_name, build_name):
        '''
        Delete build object, root_tree reference and all stored files.
        '''
        assert elita.util.type_check.is_string(app_name)
        assert elita.util.type_check.is_string(build_name)
        assert app_name and build_name

        root_path = ('app', app_name, 'builds', build_name)
        self.mongo_service.rm_roottree(root_path)
        self.RmThreadLocalRootTree(root_path)
        self.mongo_service.delete('builds', {'app_name': app_name, 'build_name': build_name})
        self.DeleteBuildStorage(app_name, build_name)

    def GetBuild(self, app_name, build_name):
        '''
        Get build document
        '''
        assert elita.util.type_check.is_string(app_name)
        assert elita.util.type_check.is_string(build_name)
        assert app_name and build_name
        assert app_name in self.root['app']
        assert build_name in self.root['app'][app_name]['builds']
        doc = self.mongo_service.get('builds', {'app_name': app_name, 'build_name': build_name})
        doc['created_datetime'] = doc['_id'].generation_time
        return {k: doc[k] for k in doc if k[0] != '_'}


class UserDataService(GenericChildDataService):

    def NewUser(self, name, pw, perms, attribs):
        '''
        Create a new user object and insert root_tree references for both the user and the computed permissions
        endpoint. Pipe parameters into User object to get the pw hashed, etc.
        '''
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_string(pw)
        assert isinstance(attribs, dict)
        assert isinstance(perms, dict)
        assert name and pw and perms

        userobj = models.User({
            'username': name,
            'permissions': perms,
            'password': pw,
            'attributes': attribs
        })
        uid = self.mongo_service.create_new('users', {'username': userobj.username}, 'User', userobj.get_doc())
        pid = self.mongo_service.create_new('userpermissions', {'username': userobj.username}, 'UserPermissions', {
            "username": userobj.username,
            "applications": list(),
            "actions": dict(),
            "servers": list()
        })
        self.mongo_service.update_roottree(('global', 'users', userobj.username), 'users', uid)
        self.AddThreadLocalRootTree(('global', 'users', userobj.username))
        self.mongo_service.update_roottree(('global', 'users', userobj.username, 'permissions'), 'userpermissions', pid)
        self.AddThreadLocalRootTree(('global', 'users', userobj.username, 'permissions'))
        return uid, pid

    def GetUserTokens(self, username):
        '''
        Get all auth tokens associated with user
        '''
        assert elita.util.type_check.is_string(username)
        assert username
        return [d['token'] for d in self.mongo_service.get('tokens', {'username': username}, multi=True, empty=True)]

    def GetUserFromToken(self, token):
        '''
        Get username associated with token
        '''
        assert elita.util.type_check.is_string(token)
        assert token
        return self.mongo_service.get('tokens', {'token': token})['username']

    def GetAllTokens(self):
        '''
        Get all valid tokens
        '''
        return [token for token in self.root['global']['tokens'] if token[0] != '_']

    def NewToken(self, username):
        '''
        Create new auth token associated with username and insert reference into root_tree
        '''
        assert elita.util.type_check.is_string(username)
        assert username

        token = models.Token({
            'username': username
        })
        tid = self.mongo_service.create_new('tokens', {'username': username, 'token': token.token}, 'Token',
                                            token.get_doc())
        self.mongo_service.update_roottree(('global', 'tokens', token.token), 'tokens', tid)
        self.AddThreadLocalRootTree(('global', 'tokens', token.token))
        return token

    def GetUsers(self):
        '''
        Get all valid users
        '''
        return [user for user in self.root['global']['users'] if user[0] != '_']

    def GetUser(self, username):
        '''
        Get user document
        '''
        assert elita.util.type_check.is_string(username)
        assert username
        doc = self.mongo_service.get('users', {'username': username})
        doc['created_datetime'] = doc['_id'].generation_time
        return {k: doc[k] for k in doc if k[0] != '_'}

    def DeleteUser(self, name):
        '''
        Delete a single user and root_tree reference
        '''
        assert name
        assert elita.util.type_check.is_string(name)
        self.mongo_service.rm_roottree(('global', 'users', name))
        self.RmThreadLocalRootTree(('global', 'users', name))
        self.mongo_service.delete('users', {'username': name})

    def DeleteToken(self, token):
        '''
        Delete a token and root_tree reference
        '''
        assert token
        assert elita.util.type_check.is_string(token)
        self.mongo_service.rm_roottree(('global', 'tokens', token))
        self.RmThreadLocalRootTree(('global', 'tokens', token))
        self.mongo_service.delete('tokens', {'token': token})

    def UpdateUser(self, name, doc):
        '''
        Update user with keys in doc
        '''
        assert name and doc
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_dictlike(doc) or elita.util.type_check.is_seq(doc)
        assert name in self.root['global']['users']

        if elita.util.type_check.is_dictlike(doc) and "password" in doc:
            user = models.User(doc)
            doc['hashed_pw'] = user.hashed_pw
            doc['salt'] = user.salt
            doc['password'] = None
        elif elita.util.type_check.is_seq(doc):
            # If this is a JSON Patch, we need to do magic if user is trying to change password
            # we replace JSON Patch operation to replace password field with operations to replace
            # hashed_pw and salt instead. We have to do it in-place by splicing because the JSON Patch
            # could be arbitrarily complex.
            splice_index = None
            splices = []
            for i, op in enumerate(doc):
                if not ("op" in op and "path" in op and "value" in op):
                    return False
                for k in ("salt", "hashed_pw"):
                    if k in op["path"]:
                        return False
                path_split = str(op["path"]).split('/')
                if len(path_split) < 2:
                    return False
                if path_split[1] == "password":
                    if elita.util.type_check.is_string(op["value"]) and op["op"] == "replace":
                        user = models.User({"password": op["value"]})
                        splice_index = i
                        splices.append({"op": "replace", "path": "/password", "value": None})
                        splices.append({"op": "replace", "path": "/hashed_pw", "value": user.hashed_pw})
                        splices.append({"op": "replace", "path": "/salt", "value": user.salt})
                    else:
                        return False

            if splice_index is not None:  # don't use truthiness because 0 is valid
                doc[splice_index] = splices[0]
                doc.insert(splice_index+1, splices[1])
                doc.insert(splice_index+2, splices[2])

        if elita.util.type_check.is_dictlike(doc):
            self.UpdateObject('users', {'username': name}, doc)
        else:
            try:
                self.UpdateObjectFromPatch('users', {'username': name}, doc)
            except:
                return False
        return True


class ApplicationDataService(GenericChildDataService):
    def GetApplications(self):
        '''
        Get all applications. Pull from in-memory root_tree rather than mongo for speed.
        '''
        return [app for app in self.root['app'] if app[0] != '_']

    def GetApplication(self, app_name):
        '''
        Get application document
        '''
        assert app_name
        assert elita.util.type_check.is_string(app_name)
        doc = self.mongo_service.get('applications', {'app_name': app_name})
        doc['created_datetime'] = doc['_id'].generation_time
        return {k: doc[k] for k in doc if k[0] != '_'}

    def NewApplication(self, app_name):
        '''
        Create new application and all subcontainers and root_tree sub-references
        '''
        assert app_name
        assert elita.util.type_check.is_string(app_name)
        aid = self.mongo_service.create_new('applications', {'app_name': app_name}, 'Application', {})
        root_doc = {
            "builds": {"_doc": bson.DBRef('containers', self.NewContainer("BuildContainer", "builds", app_name))},
            "actions": {"_doc": bson.DBRef('containers', self.NewContainer("ActionContainer", "actions", app_name))},
            "gitrepos": {"_doc": bson.DBRef('containers', self.NewContainer("GitRepoContainer", "gitrepos", app_name))},
            "gitdeploys": {"_doc": bson.DBRef('containers', self.NewContainer("GitDeployContainer", "gitdeploys", app_name))},
            "deployments": {"_doc": bson.DBRef('containers', self.NewContainer("DeploymentContainer", "deployments", app_name))},
            "groups": {"_doc": bson.DBRef('containers', self.NewContainer("GroupContainer", "groups", app_name))},
            "packagemaps": {"_doc": bson.DBRef('containers', self.NewContainer("PackageMapContainer", "packagemaps", app_name))}
        }
        res = self.mongo_service.update_roottree(('app', app_name), 'applications', aid, doc=root_doc)
        self.AddThreadLocalRootTree(('app', app_name))
        return res

    def DeleteApplication(self, app_name):
        '''
        Delete application and all root_tree references and sub-objects.
        '''
        assert app_name
        assert elita.util.type_check.is_string(app_name)
        self.mongo_service.rm_roottree(('app', app_name))
        self.mongo_service.delete('applications', {'app_name': app_name})
        self.mongo_service.delete('builds', {'app_name': app_name})
        self.mongo_service.delete('gitrepos', {'application': app_name})
        self.mongo_service.delete('gitdeploys', {'application': app_name})
        self.mongo_service.delete('deployments', {'application': app_name})
        self.mongo_service.delete('groups', {'application': app_name})
        self.mongo_service.delete('packagemaps', {'application': app_name})
        self.RmThreadLocalRootTree(('app', app_name))

    def GetApplicationCensus(self, app_name):
        '''
        Generates a census of all environments, groups, servers and builds deployed:
        {
          "env_name": {
            "group_name": {
                "server_name": {
                    "gitdeploy_name": {
                        "committed": "build_name",
                        "deployed": "build_name"
                }
            }
        }
        '''
        assert app_name
        assert elita.util.type_check.is_string(app_name)
        groups = [d['name'] for d in self.mongo_service.get('groups', {'application': app_name}, multi=True, empty=True)]
        envs = list({d['environment'] for d in self.mongo_service.get('servers', {}, multi=True, empty=True)})
        census = dict()
        for e in envs:
            census[e] = dict()
            for g in groups:
                g_servers = self.deps['GroupDataService'].GetGroupServers(app_name, g, environments=[e])
                census[e][g] = dict()
                for s in g_servers:
                    census[e][g][s] = dict()
                    group_doc = self.deps['GroupDataService'].GetGroup(app_name, g)
                    for gd in group_doc['gitdeploys']:
                        gdl = gd if isinstance(gd, list) else [gd]
                        for gd in gdl:
                            gd_doc = self.deps['GitDataService'].GetGitDeploy(app_name, gd)
                            census[e][g][s][gd] = {
                                "committed": gd_doc['location']['gitrepo']['last_build'],
                                "deployed": gd_doc['deployed_build']
                            }
                    if len(census[e][g][s]) == 0:
                        del census[e][g][s]
                if len(census[e][g]) == 0:
                    del census[e][g]
            if len(census[e]) == 0:
                del census[e]
        return census

    def UpdateApplication(self, app, doc):
        '''
        Update application with keys in doc
        '''
        assert app and doc
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_dictlike(doc) or elita.util.type_check.is_seq(doc)
        assert app in self.root['app']

        if elita.util.type_check.is_dictlike(doc):
            self.UpdateObject('applications', {'app_name': app}, doc)
        else:
            try:
                self.UpdateObjectFromPatch('applications', {'app_name': app}, doc)
            except:
                return False
        return True

class PackageMapDataService(GenericChildDataService):
    def GetPackageMaps(self, app):
        '''
        Get all packagemaps for application
        '''
        assert app
        assert elita.util.type_check.is_string(app)
        assert app in self.root['app']
        return [pm for pm in self.root['app'][app]['packagemaps'] if pm[0] != '_']

    def GetPackageMap(self, app, name):
        '''
        Get document for packagemap
        '''
        assert app and name
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        doc = self.mongo_service.get('packagemaps', {'application': app, 'name': name})
        doc['created_datetime'] = doc['_id'].generation_time
        return {k: doc[k] for k in doc if k[0] != '_'}

    def NewPackageMap(self, app, name, packages, attributes=None):
        '''
        Create new packagemap

        @type app: str
        @type name: str
        @type packages: dict
        @type attributes: dict | None
        '''
        assert app and name and packages
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_dictlike(packages)
        assert elita.util.type_check.is_optional_dict(attributes)
        attributes = attributes if attributes else {}
        pm = models.PackageMap({
            'application': app,
            'name': name,
            'packages': packages,
            'attributes': attributes
        })
        pmid = self.mongo_service.create_new('packagemaps', {'application': app, 'name': name}, 'PackageMap', pm.get_doc())
        self.mongo_service.update_roottree(('app', app, 'packagemaps', name), 'packagemaps', pmid)
        self.AddThreadLocalRootTree(('app', app, 'packagemaps', name))

    def DeletePackageMap(self, app, name):
        '''
        Delete a packagemap object and root_tree reference
        '''
        assert app and name
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        self.mongo_service.rm_roottree(('app', app, 'packagemaps', name))
        self.RmThreadLocalRootTree(('app', app, 'packagemaps', name))
        self.mongo_service.delete('packagemaps', {'application': app, 'name': name})

    def UpdatePackageMap(self, app, name, doc):
        '''
        Update packagemap with keys in doc
        '''
        assert app and name and doc
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_dictlike(doc) or elita.util.type_check.is_seq(doc)
        assert app in self.root['app']
        assert name in self.root['app'][app]['packagemaps']

        if elita.util.type_check.is_dictlike(doc):
            self.UpdateObject('packagemaps', {'application': app, 'name': name}, doc)
        else:
            try:
                self.UpdateObjectFromPatch('packagemaps', {'application': app, 'name': name}, doc)
            except:
                return False
        return True

class GroupDataService(GenericChildDataService):
    def GetGroups(self, app):
        '''
        Get all groups for application.
        '''
        assert app
        assert elita.util.type_check.is_string(app)
        assert app in self.root['app']
        return [group for group in self.root['app'][app]['groups'] if group[0] != '_']

    def GetGroup(self, app, name):
        '''
        Get document for application group
        '''
        assert app and name
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        doc = self.mongo_service.get('groups', {'application': app, 'name': name})
        doc['servers'] = self.GetGroupServers(app, name, group_doc=doc)
        doc['created_datetime'] = doc['_id'].generation_time
        return {k: doc[k] for k in doc if k[0] != '_'}

    def NewGroup(self, app, name, gitdeploys, rolling_deploy=False, description="", attributes=None):
        '''
        Create new application group.

        @type app: str
        @type name: str
        @type gitdeploys: list[str]
        @type rolling_deploys: True | False
        @type description: str
        @type attributes: dict | None
        '''
        assert app and name and gitdeploys
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_seq(gitdeploys)
        assert elita.util.type_check.is_string(description)
        assert elita.util.type_check.is_optional_dict(attributes)
        attributes = attributes if attributes else {}
        gp = models.Group({
            "application": app,
            "name": name,
            "description": description,
            "gitdeploys": gitdeploys,
            "attributes": attributes,
            "rolling_deploy": rolling_deploy
        })

        gid = self.mongo_service.create_new('groups', {'application': app, 'name': name}, 'Group', gp.get_doc())
        self.mongo_service.update_roottree(('app', app, 'groups', name), 'groups', gid)
        self.AddThreadLocalRootTree(('app', app, 'groups', name))

    def DeleteGroup(self, app, name):
        '''
        Delete a group object and root_tree reference
        '''
        assert app and name
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        self.mongo_service.rm_roottree(('app', app, 'groups', name))
        self.RmThreadLocalRootTree(('app', app, 'groups', name))
        self.mongo_service.delete('groups', {'application': app, 'name': name})

    def GetGroupServers(self, app, name, environments=None, group_doc=None):
        '''
        Build sets from initialized servers in each gitdeploy in the group, then take intersection of all the sets
        If environments specified, take intersection with that set as well

        Allow caller to provide group_doc to prevent infinite recursion from GetGroup calling GetGroupServers
        '''
        assert app and name
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert app in self.root['app']
        assert name in self.root['app'][app]['groups']
        if not group_doc:
            group = self.GetGroup(app, name)
        else:
            group = group_doc
        # this is ugly. gitdeploys can either be a list of strings or a list of lists. We have to flatten the
        # list of lists if necessary
        server_sets = [set(self.deps['GitDataService'].GetGitDeploy(app, gd)['servers']) for sublist in group['gitdeploys'] for gd in sublist] if isinstance(group['gitdeploys'][0], list) else [set(self.deps['GitDataService'].GetGitDeploy(app, gd)['servers']) for gd in group['gitdeploys']]
        if environments:
            server_env_set = set()
            envs = self.deps['ServerDataService'].GetEnvironments()
            for e in environments:
                assert e in envs
                server_env_set = set(envs[e]).union(server_env_set)
            server_sets.append(server_env_set)
        return list(set.intersection(*server_sets))

    def UpdateGroup(self, app, name, doc):
        '''
        Update group with keys in doc
        '''
        assert app and name and doc
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_dictlike(doc) or elita.util.type_check.is_seq(doc)
        assert app in self.root['app']
        assert name in self.root['app'][app]['groups']

        if elita.util.type_check.is_dictlike(doc):
            self.UpdateObject('groups', {'application': app, 'name': name}, doc)
        else:
            try:
                self.UpdateObjectFromPatch('groups', {'application': app, 'name': name}, doc)
            except:
                return False
        return True

class JobDataService(GenericChildDataService):
    def GetAllActions(self, app_name):
        '''
        Get all actions associated with application. Get it from root_tree because the actions are dynamically populated
        at the start of each request.
        '''
        assert app_name
        assert elita.util.type_check.is_string(app_name)
        if 'actions' in self.root['app'][app_name]:
            return [action for action in self.root['app'][app_name]['actions'] if action[0] != '_']

    def GetAction(self, app_name, action_name):
        '''
        Get details (name, description, parameters) about all actions associated with application
        '''
        assert app_name and action_name
        assert elita.util.type_check.is_string(app_name)
        assert elita.util.type_check.is_string(action_name)
        actions = self.deps['ActionService'].get_action_details(app_name, action_name)
        return {k: actions[k] for k in actions if k is not "callable"}

    def NewJob(self, name, job_type, data):
        '''
        Create new job object.

        data parameter can be anything serializable (including None) so that's all we will check for
        '''
        assert name and job_type
        assert elita.util.type_check.is_serializable(data)
        job = models.Job({
            'status': "running",
            'name': name,
            'job_type': job_type,
            'data': data,
            'attributes': {
                'name': name
            }
        })
        jid = self.mongo_service.create_new('jobs', {'job_id': str(job.job_id)}, 'Job', job.get_doc())
        self.mongo_service.update_roottree(('job', str(job.job_id)), 'jobs', jid)
        self.AddThreadLocalRootTree(('job', str(job.job_id)))
        return job

    def NewJobData(self, data):
        '''
        Insert new job_data record. Called by async jobs to log progress. Data inserted here can be viewed by user
        by polling the respective job object endpoint.

        Only valid to be called in an asynch context, so assert we have a valid job_id
        '''
        assert data
        assert elita.util.type_check.is_serializable(data)
        assert self.job_id
        elita.util.change_dict_keys(data, '.', '_')
        self.mongo_service.create_new('job_data', {}, None, {
            'job_id': self.job_id,
            'data': data
        }, remove_existing=False)

    def GetJobs(self, active):
        '''
        Get all actively running jobs. Pulling from mongo could possibly be more efficient (maybe) than using
        in-memory root_tree because we're querying on the status field
        '''
        return [d['job_id'] for d in self.mongo_service.get('jobs', {'status': 'running'}, multi=True)]

    def GetJobData(self, job_id):
        '''
        Get job data for a specific job sorted by created_datetime (ascending)
        '''
        assert job_id
        assert elita.util.type_check.is_string(job_id)
        return sorted([{'created_datetime': d['_id'].generation_time.isoformat(' '), 'data': d['data']} for
                       d in self.mongo_service.get('job_data', {'job_id': job_id}, multi=True, empty=True)],
                      key=lambda k: k['created_datetime'])

    def SaveJobResults(self, results):
        '''
        Called at the end of async jobs. Changes state of job object to reflect job completion.
        '''
        assert self.job_id
        assert elita.util.type_check.is_serializable(results)
        now = datetime.datetime.now(tz=pytz.utc)
        doc = self.mongo_service.get('jobs', {'job_id': self.job_id})
        assert doc and elita.util.type_check.is_dictlike(doc) and '_id' in doc
        results_sanitized = copy.deepcopy(results)
        elita.util.change_dict_keys(results_sanitized, '.', '_')
        diff = (now - doc['_id'].generation_time).total_seconds()
        self.mongo_service.modify('jobs', {'job_id': self.job_id}, ('status',), "completed")
        self.mongo_service.modify('jobs', {'job_id': self.job_id}, ('completed_datetime',), now)
        self.mongo_service.modify('jobs', {'job_id': self.job_id}, ('duration_in_seconds',), diff)
        self.NewJobData({"completed_results": results_sanitized})

    def NewAction(self, app_name, action_name, params):
        '''
        Register new dynamically-loaded action in root_tree. These are loaded from plugins at the start of each request
        Note that action is added to in-memory root_tree object (not the root_tree record in mongo) because it is not
        persistent. Note further that this is *our* (meaning this thread's) root_tree and will only be in effect for the
        duration of this request, so we don't care about any root_tree updates by other threads running concurrently
        '''
        assert app_name and action_name
        assert elita.util.type_check.is_string(app_name)
        assert elita.util.type_check.is_string(action_name)
        assert elita.util.type_check.is_optional_seq(params)
        logging.debug("NewAction: app_name: {}".format(app_name))
        logging.debug("NewAction: action_name: {}".format(action_name))
        if app_name in self.deps['ApplicationDataService'].GetApplications():
            assert app_name in self.root['app']
            assert 'actions' in self.root['app'][app_name]
            assert elita.util.type_check.is_dictlike(self.root['app'][app_name]['actions'])
            self.root['app'][app_name]['actions'][action_name] = models.Action(app_name, action_name, params, self)
        else:
            logging.debug("NewAction: application '{}' not found".format(app_name))

    def ExecuteAction(self, app_name, action_name, params):
        '''
        Spawn async job for an action
        '''
        assert app_name and action_name and params
        assert elita.util.type_check.is_string(app_name)
        assert elita.util.type_check.is_string(action_name)
        assert elita.util.type_check.is_dictlike(params)
        return self.deps['ActionService'].async(app_name, action_name, params)

class ServerDataService(GenericChildDataService):
    def GetServers(self):
        '''
        Return a list of all extant server objects
        '''
        return [k for k in self.root['server'].keys() if k[0] != '_' and k != 'environments']

    def NewServer(self, name, attribs, environment, existing=False):
        '''
        Create a new server object
        '''
        server = models.Server({
            'name': name,
            'status': 'new',
            'server_type': 'unknown',
            'environment': environment,
            'attributes': attribs
        })
        sid = self.mongo_service.create_new('servers', {'name': name}, 'Server', server.get_doc())
        self.mongo_service.update_roottree(('server', name), 'servers', sid, doc={
            "gitdeploys": self.NewContainer('GitDeployContainer', name, "gitdeploys")
        })
        self.AddThreadLocalRootTree(('server', name))
        return {
            'NewServer': {
                'name': name,
                'environment': environment,
                'attributes': attribs,
                'status': 'ok'
            }
        }

    def UpdateServer(self, name, doc):
        '''
        Change existing server object with data in doc
        '''
        assert name and doc
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_dictlike(doc) or elita.util.type_check.is_seq(doc)
        assert name in self.root['server']

        if elita.util.type_check.is_dictlike(doc):
            self.UpdateObject('servers', {'name': name}, doc)
        else:
            try:
                self.UpdateObjectFromPatch('servers', {'name': name}, doc)
            except:
                return False
        return True

    def DeleteServer(self, name):
        '''
        Delete a server object
        '''
        assert name
        assert elita.util.type_check.is_string(name)
        assert name in self.root['server']
        self.mongo_service.rm_roottree(('server', name))
        self.RmThreadLocalRootTree(('server', name))
        self.mongo_service.delete('servers', {'name': name})

    def GetGitDeploys(self, name):
        '''
        Get all gitdeploys initialized on a server. The canonical data source is the gitdeploy object (which contains
        a list of servers it's been initialized on)
        '''
        assert name
        assert elita.util.type_check.is_string(name)
        assert name in self.root['server']
        gitdeploys = self.mongo_service.get('gitdeploys', {'servers': {'$in': [name]}}, multi=True, empty=True)
        if gitdeploys:
            return [{'application': gd['application'], 'gitdeploy_name': gd['name']} for gd in gitdeploys]
        else:
            return []

    def GetEnvironments(self):
        '''
        Get a census of all environments. "environment" is just a tag associated with a server upon creation, so get all
        tags and dedupe.
        '''
        environments = dict()
        for sd in self.mongo_service.get('servers', {}, multi=True):
            assert elita.util.type_check.is_dictlike(sd)
            assert 'environment' in sd
            if sd['environment'] not in environments:
                environments[sd['environment']] = list()
            environments[sd['environment']].append(sd['name'])
        return environments

class GitDataService(GenericChildDataService):
    def NewGitDeploy(self, name, app_name, package, options, actions, location, attributes):
        '''
        Create new gitdeploy object. One of a few New* methods that returns status of success/failure to the view layer
        @rtype dict
        '''
        assert name and app_name and location
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_string(app_name)
        assert elita.util.type_check.is_dictlike(location)
        assert all([k in location for k in ('gitrepo', 'path', 'default_branch')])
        assert app_name in self.root['app']
        assert elita.util.type_check.is_optional_str(package)
        assert elita.util.type_check.is_optional_dict(options)
        assert elita.util.type_check.is_optional_dict(actions)
        assert elita.util.type_check.is_optional_dict(attributes)

        #get associated gitrepo
        gitrepo_doc = self.mongo_service.get('gitrepos', {'name': location['gitrepo']})
        logging.debug("NewGitDeploy: gitrepo_doc: {}".format(gitrepo_doc))
        if not gitrepo_doc:
            return {'error': "invalid gitrepo (not found)"}

        #replace gitrepo name with DBRef
        location['gitrepo'] = bson.DBRef("gitrepos", gitrepo_doc['_id'])

        #construct gitdeploy document
        gd_obj = models.GitDeploy({})
        gd_doc = gd_obj.get_doc()
        gd_doc['name'] = name
        gd_doc['application'] = app_name
        gd_doc['location'] = location
        gd_doc['attributes'] = attributes if attributes else {}
        gd_doc['package'] = package

        #override defaults if specified
        if options:
            for k in options:
                if k in gd_doc['options']:
                    gd_doc['options'][k] = options[k]
        if actions:
            elita.util.change_dict_keys(actions, '.', EMBEDDED_YAML_DOT_REPLACEMENT)
            for k in actions:
                if k in gd_doc['actions']:
                    gd_doc['actions'][k] = actions[k]
        gdid = self.mongo_service.create_new('gitdeploys', {'name': name, 'application': app_name}, 'GitDeploy', gd_doc)
        self.mongo_service.update_roottree(('app', app_name, 'gitdeploys', name), 'gitdeploys', gdid)
        self.AddThreadLocalRootTree(('app', app_name, 'gitdeploys', name))
        return {"ok": "done"}

    def GetGitDeploys(self, app):
        '''
        Get all gitdeploys associated with application

        @rtype: list
        '''
        assert app
        assert elita.util.type_check.is_string(app)
        assert app in self.root['app']
        return [k for k in self.root['app'][app]['gitdeploys'] if k[0] != '_']


    def GetGitDeploy(self, app, name):
        '''
        Get gitdeploy document. Dereference embedded DBrefs for convenience.

        @rtype: dict
        '''
        assert app and name
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert app in self.root['app']
        assert name in self.root['app'][app]['gitdeploys']

        doc = self.mongo_service.get('gitdeploys', {'name': name, 'application': app})
        doc['created_datetime'] = doc['_id'].generation_time
        assert 'location' in doc
        assert 'gitrepo' in doc['location']
        #dereference embedded dbrefs
        doc['location']['gitrepo'] = self.mongo_service.dereference(doc['location']['gitrepo'])
        assert doc['location']['gitrepo']
        assert all([k in doc['location']['gitrepo'] for k in ('keypair', 'gitprovider')])
        doc['location']['gitrepo']['keypair'] = self.mongo_service.dereference(doc['location']['gitrepo']['keypair'])
        assert doc['location']['gitrepo']['keypair']
        doc['location']['gitrepo']['gitprovider'] = self.mongo_service.dereference(doc['location']['gitrepo']['gitprovider'])
        assert doc['location']['gitrepo']['gitprovider']
        return {k: doc[k] for k in doc if k[0] != '_'}

    def UpdateGitDeploy(self, app, name, doc):
        '''
        Update gitdeploy object with the data in doc
        '''
        assert app and name and doc
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_dictlike(doc) or elita.util.type_check.is_seq(doc)
        assert app in self.root['app']
        assert name in self.root['app'][app]['gitdeploys']

        if elita.util.type_check.is_dictlike(doc):
            #clean up any actions
            if 'actions' in doc:
                elita.util.change_dict_keys(doc['actions'], '.', EMBEDDED_YAML_DOT_REPLACEMENT)

            #replace gitrepo with DBRef if necessary
            if 'location' in doc and 'gitrepo' in doc['location']:
                grd = self.mongo_service.get('gitrepos', {'name': doc['location']['gitrepo'], 'application': app})
                assert grd
                doc['location']['gitrepo'] = bson.DBRef('gitrepos', grd['_id'])

            self.UpdateObject('gitdeploys', {'name': name, 'application': app}, doc)
        else:
            try:
                self.UpdateObjectFromPatch('gitdeploys', {'name': name, 'application': app}, doc)
            except:
                return False
        return True


    def DeleteGitDeploy(self, app, name):
        '''
        Delete a gitdeploy object and the root_tree reference
        '''
        assert app and name
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert app in self.root['app']
        assert name in self.root['app'][app]['gitdeploys']

        self.mongo_service.rm_roottree(('app', app, 'gitdeploys', name))
        self.RmThreadLocalRootTree(('app', app, 'gitdeploys', name))
        self.mongo_service.delete('gitdeploys', {'name': name, 'application': app})

    def GetGitProviders(self):
        '''
        Get all gitproviders

        @rtype: list(str) | None
        '''
        return [k for k in self.root['global']['gitproviders'] if k[0] != '_']

    def GetGitProvider(self, name):
        '''
        Get gitprovider document

        @rtype: dict | None
        '''
        assert name
        assert elita.util.type_check.is_string(name)
        assert name in self.root['global']['gitproviders']

        doc = self.mongo_service.get('gitproviders', {'name': name})
        doc['created_datetime'] = doc['_id'].generation_time
        return {k: doc[k] for k in doc if k[0] != '_'}

    def NewGitProvider(self, name, provider_type, auth):
        '''
        Create new gitprovider object
        '''
        assert name and type and auth
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_string(provider_type)
        assert provider_type in ('bitbucket', 'github')
        assert elita.util.type_check.is_dictlike(auth)
        assert 'username' in auth and 'password' in auth
        assert elita.util.type_check.is_string(auth['username'])
        assert elita.util.type_check.is_string(auth['password'])

        gpo = models.GitProvider({
            'name': name,
            'type': provider_type,
            'auth': auth
        })

        gpid = self.mongo_service.create_new('gitproviders', {'name': name}, 'GitProvider', gpo.get_doc())
        self.mongo_service.update_roottree(('global', 'gitproviders', name), 'gitproviders', gpid)
        self.AddThreadLocalRootTree(('global', 'gitproviders', name))

    def UpdateGitProvider(self, name, doc):
        '''
        Modify gitprovider with the data in doc
        '''
        assert name and doc
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_dictlike(doc) or elita.util.type_check.is_seq(doc)
        assert name in self.root['global']['gitproviders']

        if elita.util.type_check.is_dictlike(doc):
            self.UpdateObject('gitproviders', {'name': name}, doc)
        else:
            try:
                self.UpdateObjectFromPatch('gitproviders', {'name': name}, doc)
            except:
                return False
        return True

    def DeleteGitProvider(self, name):
        '''
        Delete gitprovider object and root_tree reference
        '''
        assert name
        assert elita.util.type_check.is_string(name)
        assert name in self.root['global']['gitproviders']

        self.mongo_service.rm_roottree(('global', 'gitproviders', name))
        self.RmThreadLocalRootTree(('global', 'gitproviders', name))
        self.mongo_service.delete('gitproviders', {'name': name})

    def GetGitRepos(self, app):
        '''
        Get a list of all gitrepos associated with application

        @rtype: list(dict)
        '''
        assert app
        assert elita.util.type_check.is_string(app)
        assert app in self.root['app']

        return [k for k in self.root['app'][app]['gitrepos'] if k[0] != '_']

    def GetGitRepo(self, app, name):
        '''
        Get gitrepo document

        @rtype: dict
        '''
        assert app and name
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert app in self.root['app']
        assert name in self.root['app'][app]['gitrepos']

        doc = self.mongo_service.get('gitrepos', {'name': name, 'application': app})
        assert doc and 'gitprovider' in doc and 'keypair' in doc
        doc['created_datetime'] = doc['_id'].generation_time
        gitprovider = self.mongo_service.dereference(doc['gitprovider'])
        doc['gitprovider'] = {k: gitprovider[k] for k in gitprovider if k[0] != '_'}
        keypair = self.mongo_service.dereference(doc['keypair'])
        doc['keypair'] = {k: keypair[k] for k in keypair if k[0] != '_'}
        return {k: doc[k] for k in doc if k[0] != '_'}

    def NewGitRepo(self, app, name, keypair, gitprovider, uri):
        '''
        Create new gitrepo object

        @rtype: dict
        '''
        assert app and name and keypair and gitprovider
        assert all([elita.util.type_check.is_string(p) for p in (app, name, keypair, gitprovider)])
        assert elita.util.type_check.is_optional_str(uri)
        assert app in self.root['app']
        assert keypair in self.root['global']['keypairs']
        assert gitprovider in self.root['global']['gitproviders']

        #get docs so we can generate DBRefs
        kp_doc = self.mongo_service.get('keypairs', {'name': keypair})
        gp_doc = self.mongo_service.get('gitproviders', {'name': gitprovider})
        if not gp_doc:
            return {'NewGitRepo': "gitprovider '{}' is unknown".format(gitprovider)}
        if not kp_doc:
            return {'NewGitRepo': "keypair '{}' is unknown".format(keypair)}

        gro = models.GitRepo({
            'name': name,
            'application': app,
            'keypair': bson.DBRef("keypairs", kp_doc['_id']),
            'gitprovider': bson.DBRef("gitproviders", gp_doc['_id']),
            'uri': uri,
            'last_build': None
        })

        grid = self.mongo_service.create_new('gitrepos', {'name': name, 'application': app}, 'GitRepo', gro.get_doc())
        self.mongo_service.update_roottree(('app', app, 'gitrepos', name), 'gitrepos', grid)
        self.AddThreadLocalRootTree(('app', app, 'gitrepos', name))
        return {'NewGitRepo': 'ok'}

    def UpdateGitRepo(self, app, name, doc):
        '''
        Update gitrepo with the data in doc
        '''
        assert app and name and doc
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_dictlike(doc) or elita.util.type_check.is_seq(doc)
        assert app in self.root['app']

        if elita.util.type_check.is_dictlike(doc):
            self.UpdateObject('gitrepos', {'name': name, 'application': app}, doc)
        else:
            try:
                self.UpdateObjectFromPatch('gitrepos', {'name': name, 'application': app}, doc)
            except:
                return False
        return True

    def DeleteGitRepo(self, app, name):
        '''
        Delete gitrepo object and root_tree reference
        '''
        assert app and name
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert app in self.root['app']
        assert name in self.root['app'][app]['gitrepos']

        self.mongo_service.rm_roottree(('app', app, 'gitrepos', name))
        self.RmThreadLocalRootTree(('app', app, 'gitrepos', name))
        self.mongo_service.delete('gitrepos', {'name': name, 'application': app})

class DeploymentDataService(GenericChildDataService):
    def NewDeployment(self, app, build_name, environments, groups, servers, gitdeploys, username, options):
        '''
        Create new deployment object

        @rtype: dict
        '''
        assert app and build_name and username and options and ((environments and groups) or (servers and gitdeploys))
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(build_name)
        assert elita.util.type_check.is_string(username)
        assert elita.util.type_check.is_dictlike(options)
        assert app in self.root['app']
        assert build_name in self.root['app'][app]['builds']
        assert username in self.root['global']['users']
        assert all([not p for p in (environments, groups)]) or all([elita.util.type_check.is_seq(p) for p in (environments, groups)])
        assert all([not p for p in (servers, gitdeploys)]) or all([elita.util.type_check.is_seq(p) for p in (servers, gitdeploys)])
        assert not environments or set(environments).issubset(set(self.deps['ServerDataService'].GetEnvironments()))
        assert not groups or all([g in self.root['app'][app]['groups'] for g in groups])
        assert not servers or all([s in self.root['server'] for s in servers])
        assert not gitdeploys or all([gd in self.root['app'][app]['gitdeploys'] for gd in gitdeploys])


        dpo = models.Deployment({
            'name': "",
            'application': app,
            'build_name': build_name,
            'environments': environments,
            'groups': groups,
            'servers': servers,
            'gitdeploys': gitdeploys,
            'username': username,
            'options': options,
            'status': 'created',
            'job_id': ''
        })

        did = self.mongo_service.create_new('deployments', {}, 'Deployment', dpo.get_doc(), remove_existing=False)
        # we don't know the full deployment 'name' until it's inserted
        name = "{}_{}".format(build_name, str(did))
        self.mongo_service.modify('deployments', {'_id': did}, ('name',), name)
        self.mongo_service.update_roottree(('app', app, 'deployments', name), 'deployments', did)
        self.AddThreadLocalRootTree(('app', app, 'deployments', name))
        return {
            'NewDeployment': {
                'application': app,
                'id': name
            }
        }

    def GetDeployments(self, app, sort=False, with_details=False):
        '''
        Get a list of all deployments for application.

        sort can be either "asc" or "desc" (False indicates no sorting). Sorting always done by created_datetime
        @rtype: list(str)
        '''
        assert app
        assert elita.util.type_check.is_string(app)
        assert app in self.root['app']

        #query from mongo instead of root_tree so we can sort and get datetimes
        deployments = self.mongo_service.get('deployments', {'application': app}, multi=True, empty=True)
        #pymongo does not easily let you sort by generation_time internally, so we have to hack it here
        if sort:
            deployments = sorted(deployments, key=lambda d: d['_id'].generation_time, reverse=(sort == "desc"))
        if with_details:
            return [{"name": doc['name'],
                     "created": doc['_id'].generation_time.isoformat(' '),
                     "status": doc['status']} for doc in deployments]
        else:
            return [doc['name'] for doc in deployments]

    def GetDeployment(self, app, name):
        '''
        Get a specific deployment document
        '''
        assert app and name
        assert app in self.root['app']
        assert name in self.root['app'][app]['deployments']

        doc = self.mongo_service.get('deployments', {'application': app, 'name': name})
        doc['created_datetime'] = doc['_id'].generation_time
        return {k: doc[k] for k in doc if k[0] != '_'}

    def UpdateDeployment(self, app, name, doc):
        '''
        Modify deployment object with the data in doc
        '''
        assert app and name and doc
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_dictlike(doc) or elita.util.type_check.is_seq(doc)
        assert app in self.root['app']
        assert name in self.root['app'][app]['deployments']

        if elita.util.type_check.is_dictlike(doc):
            self.UpdateObject('deployments', {'application': app, 'name': name}, doc)
        else:
            try:
                self.UpdateObjectFromPatch('deployments', {'application': app, 'name': name}, doc)
            except:
                return False
        return True

    def InitializeDeploymentPlan(self, app, name, batches, gitrepos):
        '''
        Create the appropriate structure in the "progress" field of the deployment.

        @type app: str
        @type name: str
        @type batches: list(dict)
        @type gitdeploys: list(str)
        '''
        assert app and name and batches and gitrepos
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_seq(batches)
        assert all([elita.util.type_check.is_dictlike(b) for b in batches])
        assert elita.util.type_check.is_seq(gitrepos)  # list of all gitdeploys

        for gr in gitrepos:
            doc = {
                'progress': {
                    'phase1': {
                        'gitrepos': {
                            gr: {
                                'progress': 0,
                                'step': 'not started',
                                'changed_files': []
                            }
                        }
                    }
                }
            }
            self.UpdateDeployment(app, name, doc)

        # at a low level, deployment operates in a gitdeploy-centric way
        # but on a human level, a server-centric view is more intuitive, so we generate a list of servers per batch,
        # then the gitdeploys to be deployed on each server:
        # batch 0:
        #   server0:
        #       - gitdeployA
        #           * path: C:\foo\bar
        #           * package: webapplication
        #           * progress: 0%
        #           * state: not started
        #       - gitdeployB
        #           * progress: 10%
        #           * package: webapplication
        #           * progress: 0%
        #           * state: checking out default branch


        doc = {
            'progress': {
                'phase2': {}
            }
        }
        for i, batch in enumerate(batches):
            batch_name = 'batch{}'.format(i)
            doc['progress']['phase2'][batch_name] = {}
            for server in batch['servers']:
                doc['progress']['phase2'][batch_name][server] = {}
                for gitdeploy in batch['gitdeploys']:
                    gddoc = self.deps['GitDataService'].GetGitDeploy(app, gitdeploy)
                    if server in elita.deployment.deploy.determine_deployabe_servers(gddoc['servers'], [server]):
                        doc['progress']['phase2'][batch_name][server][gitdeploy] = {
                            'path': gddoc['location']['path'],
                            'package': gddoc['package'],
                            'progress': 0,
                            'state': 'not started'
                        }

        logging.debug('InitializeDeploymentPlan: doc: {}'.format(doc))
        self.UpdateDeployment(app, name, doc)

    def StartDeployment_Phase(self, app, name, phase):
        '''
        Mark the progress field currently_on as phaseN
        '''
        assert app and name and phase
        assert all([elita.util.type_check.is_string(p) for p in (app, name)])
        assert isinstance(phase, int) and (phase == 1 or phase == 2)
        assert app in self.root['app']
        assert name in self.root['app'][app]['deployments']

        self.UpdateDeployment(app, name, {'progress': {'currently_on': 'phase{}'.format(phase)}})

    def FailDeployment(self, app, name):
        '''
        Mark deployment as failed in event of errors
        '''
        assert app and name
        assert all([elita.util.type_check.is_string(p) for p in (app, name)])
        assert app in self.root['app']
        assert name in self.root['app'][app]['deployments']

        self.UpdateDeployment(app, name, {'progress': {'currently_on': 'failure'}})
        self.UpdateDeployment(app, name, {'status': 'error'})

    def CompleteDeployment(self, app, name):
        '''
        Mark deployment as done
        '''
        assert app and name
        assert all([elita.util.type_check.is_string(p) for p in (app, name)])
        assert app in self.root['app']
        assert name in self.root['app'][app]['deployments']

        self.UpdateDeployment(app, name, {'progress': {'currently_on': 'completed'}})

    def UpdateDeployment_Phase1(self, app, name, gitrepo, progress=None, step=None, changed_files=None):
        '''
        Phase 1 is gitrepo processing: decompressing package to local gitrepo, computing changes, commiting/pushing
        '''
        assert app and name and gitrepo
        assert all([elita.util.type_check.is_string(p) for p in (app, name, gitrepo)])
        assert (isinstance(progress, int) and 0 <= progress <= 100) or not progress
        assert elita.util.type_check.is_string(step) or elita.util.type_check.is_seq(step) or not step
        assert elita.util.type_check.is_optional_seq(changed_files)
        assert app in self.root['app']
        assert name in self.root['app'][app]['deployments']

        progress_dict = dict()
        if progress:
            progress_dict['progress'] = progress
        if step:
            progress_dict['step'] = step
        if changed_files:
            progress_dict['changed_files'] = changed_files

        self.UpdateDeployment(app, name, {'progress': {'phase1': {'gitrepos': {gitrepo: progress_dict}}}})

    def UpdateDeployment_Phase2(self, app, name, gitdeploy, servers, batch, progress=None, state=None):
        '''
        Phase 2 is performing git pulls across all remote servers. Progress is presented per server, but the backend
        deployment is done per gitdeploy (to multiple servers)
        '''
        assert app and name and gitdeploy and servers
        assert all([elita.util.type_check.is_string(p) for p in (app, name, gitdeploy)])
        assert elita.util.type_check.is_seq(servers)
        assert isinstance(batch, int) and batch >= 0
        assert app in self.root['app']
        assert name in self.root['app'][app]['deployments']

        progress_dict = {'batch{}'.format(batch): {}}

        for s in servers:
            progress_dict['batch{}'.format(batch)][s] = dict()
            progress_dict['batch{}'.format(batch)][s][gitdeploy] = dict()
            if progress:
                progress_dict['batch{}'.format(batch)][s][gitdeploy]['progress'] = progress
            if state:
                progress_dict['batch{}'.format(batch)][s][gitdeploy]['state'] = state

        self.UpdateDeployment(app, name, {'progress': {'phase2': progress_dict}})

class KeyDataService(GenericChildDataService):
    def GetKeyPairs(self):
        '''
        Get all extant keypair names
        '''
        return [k for k in self.root['global']['keypairs'] if k[0] != '_']

    def GetKeyPair(self, name):
        '''
        Get keypair doc
        '''
        assert name
        assert elita.util.type_check.is_string(name)
        assert name in self.root['global']['keypairs']

        doc = self.mongo_service.get('keypairs', {'name': name})
        doc['created_datetime'] = doc['_id'].generation_time
        return {k: doc[k] for k in doc if k[0] != '_'} if doc else None

    def NewKeyPair(self, name, attribs, key_type, private_key, public_key):
        '''
        Create new keypair object and root_tree reference
        '''
        assert name and key_type and private_key and public_key
        assert all([elita.util.type_check.is_string(p) for p in (name, key_type, private_key, public_key)])
        assert elita.util.type_check.is_optional_dict(attribs)

        try:
            kp_obj = models.KeyPair({
                "name": name,
                "attributes": attribs,
                "key_type": key_type,
                "private_key": private_key,
                "public_key": public_key
            })
        except:
            exc_type, exc_obj, tb = sys.exc_info()
            logging.debug("exception: {}, {}".format(exc_type, exc_obj))
            if exc_type == elita.elita_exceptions.InvalidPrivateKey:
                err = "Invalid private key"
            if exc_type == elita.elita_exceptions.InvalidPublicKey:
                err = "Invalid public key"
            if exc_type == elita.elita_exceptions.InvalidKeyPairType:
                err = "Invalid key type"
            else:
                err = "unknown key error"
            return {
                'NewKeyPair': {
                    'status': "error",
                    'message': err
                }
            }
        kpid = self.mongo_service.create_new('keypairs', {'name': name}, 'KeyPair', kp_obj.get_doc())
        self.mongo_service.update_roottree(('global', 'keypairs', name), 'keypairs', kpid)
        self.AddThreadLocalRootTree(('global', 'keypairs', name))
        return {
            'NewKeyPair': {
                'status': 'ok'
            }
        }

    def UpdateKeyPair(self, name, doc):
        '''
        Update key pair object with data in doc
        '''
        assert name and doc
        assert elita.util.type_check.is_string(name)
        assert elita.util.type_check.is_dictlike(doc) or elita.util.type_check.is_seq(doc)
        assert name in self.root['global']['keypairs']

        if elita.util.type_check.is_dictlike(doc):
            self.UpdateObject('keypairs', {'name': name}, doc)
        else:
            try:
                self.UpdateObjectFromPatch('keypairs', {'name': name}, doc)
            except:
                return False
        return True

    def DeleteKeyPair(self, name):
        '''
        Delete keypair object and root_tree reference
        '''
        assert name
        assert elita.util.type_check.is_string(name)
        assert name in self.root['global']['keypairs']

        self.mongo_service.rm_roottree(('global', 'keypairs', name))
        self.RmThreadLocalRootTree(('global', 'keypairs', name))
        self.mongo_service.delete('keypairs', {'name': name})


class DataService:
    '''
    DataService is an object that holds all the data-layer handling objects. A DataService instance is part of the request
    object and also passed to async jobs, etc. It is the main internal API for data handling.
    '''
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, settings, db, root, job_id=None):
        '''
        @type root: RootTree
        @type db: pymongo.database.Database
        @type settings: pyramid.registry.Registry
        @type job_id: str | None
        '''
        self.settings = settings
        self.db = db
        self.root = root
        self.mongo_service = MongoService(db)

        self.buildsvc = BuildDataService(self.mongo_service, root, settings, job_id=job_id)
        self.usersvc = UserDataService(self.mongo_service, root, settings, job_id=job_id)
        self.appsvc = ApplicationDataService(self.mongo_service, root, settings, job_id=job_id)
        self.jobsvc = JobDataService(self.mongo_service, root, settings, job_id=job_id)
        self.serversvc = ServerDataService(self.mongo_service, root, settings, job_id=job_id)
        self.gitsvc = GitDataService(self.mongo_service, root, settings, job_id=job_id)
        self.keysvc = KeyDataService(self.mongo_service, root, settings, job_id=job_id)
        self.deploysvc = DeploymentDataService(self.mongo_service, root, settings, job_id=job_id)
        self.actionsvc = ActionService(self)
        self.groupsvc = GroupDataService(self.mongo_service, root, settings, job_id=job_id)
        self.pmsvc = PackageMapDataService(self.mongo_service, root, settings, job_id=job_id)

        #cross-dependencies between child dataservice objects above
        self.appsvc.populate_dependencies({
            'ServerDataService': self.serversvc,
            'GroupDataService': self.groupsvc,
            'GitDataService': self.gitsvc
        })
        self.groupsvc.populate_dependencies({
            'ServerDataService': self.serversvc,
            'GitDataService': self.gitsvc
        })
        self.jobsvc.populate_dependencies({
            'ActionService': self.actionsvc,
            'ApplicationDataService': self.appsvc
        })
        self.deploysvc.populate_dependencies({
            'ServerDataService': self.serversvc,
            'GroupDataService': self.groupsvc,
            'GitDataService': self.gitsvc
        })

        #load all plugins and register actions/hooks
        self.actionsvc.register()

        #passed in if this is part of an async job
        self.job_id = job_id
        #super ugly below - only exists for plugin access
        if job_id is not None:
            self.salt_controller = salt_control.SaltController(self)
            self.remote_controller = salt_control.RemoteCommands(self.salt_controller)

    def GetAppKeys(self, app):
        return [k for k in self.root['app'][app] if k[0] != '_']

    def GetGlobalKeys(self):
        return [k for k in self.root['global'] if k[0] != '_']

