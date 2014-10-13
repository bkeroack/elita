import collections
import hashlib
import uuid
import base64
import os.path
import sys
import shutil
import bson
import pprint
import datetime
import pytz
import logging
import copy

import elita
from elita.crypto import keypair
from elita.deployment import deploy, salt_control
import util
import util.type_check
from deployment.gitservice import EMBEDDED_YAML_DOT_REPLACEMENT, GitDeployManager
import elita_exceptions
from elita.actions.action import ActionService

# URL model:
# root/app/
# root/app/{app_name}/builds/
# root/app/{app_name}/builds/{build_name}
# root/app/{app_name}/environments/
# root/app/{app_name}/environments/{env_name}/deployments
# root/app/{app_name}/environments/{env_name}/deployments/{deployment_id}
# root/app/{app_name}/environments/{env_name}/servers
# root/app/{app_name}/environemnt/{env_name}/servers/{server_name}

#dummy class to pass to RootService
class Request:
    db = None

class MongoService:
    # logspam
    #__metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, db):
        '''
        @type db = pymongo.database.Database
        '''
        assert db
        self.db = db

    def create_new(self, collection, keys, classname, doc, remove_existing=True):
        '''
        Creates new document in collection. Optionally, remove any existing according to keys (which specify how the
        new document is unique)

        Returns id of new document
        '''
        assert elita.util.type_check.is_string(collection)
        assert elita.util.type_check.is_dictlike(keys)
        assert elita.util.type_check.is_optional_str(classname)
        assert elita.util.type_check.is_dictlike(doc)
        assert collection
        # keys/classname are only mandatory if remove_existing=True
        assert (keys and classname and remove_existing) or not remove_existing
        if classname:
            doc['_class'] = classname
        existing = None
        if remove_existing:
            existing = [d for d in self.db[collection].find(keys)]
            for k in keys:
                doc[k] = keys[k]
            if '_id' in doc:
                del doc['_id']
        id = self.db[collection].save(doc, fsync=True)
        logging.debug("new id: {}".format(id))
        if existing and remove_existing:
            logging.warning("create_new found existing docs! deleting...(collection: {}, keys: {})".format(collection, keys))
            keys['_id'] = {'$ne': id}
            self.db[collection].remove(keys)
        return id

    def modify(self, collection, keys, path, doc_or_obj):
        '''
        Modifies document with the keys in doc. Does so atomically but remember that any key will overwrite the existing
        key.

        doc_or_obj could be None, zero, etc.

        Returns boolean indicating success
        '''
        assert hasattr(path, '__iter__')
        assert path
        assert elita.util.type_check.is_string(collection)
        assert isinstance(keys, dict)
        assert collection and keys
        dlist = [d for d in self.db[collection].find(keys)]
        assert dlist
        canonical_id = dlist[0]['_id']
        if len(dlist) > 1:
            logging.warning("Found duplicate entries for query {} in collection {}; using the first and removing others"
                            .format(keys, collection))
            keys['_id'] = {'$ne': canonical_id}
            self.db[collection].remove(keys)
        path_dot_notation = '.'.join(path)
        result = self.db[collection].update({'_id': canonical_id}, {'$set': {path_dot_notation: doc_or_obj}}, fsync=True)
        return result['n'] == 1 and result['updatedExisting'] and not result['err']

    def delete(self, collection, keys):
        '''
        Drop a document from the collection

        Return whatever pymongo returns for deletion
        '''
        assert elita.util.type_check.is_string(collection)
        assert isinstance(keys, dict)
        assert collection and keys
        dlist = [d for d in self.db[collection].find(keys)]
        assert dlist
        if len(dlist) > 1:
            logging.warning("Found duplicate entries for query {} in collection {}; removing all".format(keys,
                                                                                                        collection))
        return self.db[collection].remove(keys, fsync=True)

    def update_roottree(self, path, collection, id, doc=None):
        '''
        Update the root tree at path [must be a tuple of indices: ('app', 'myapp', 'builds', '123-foo')] with DBRef
        Optional doc can be passed in which will be inserted into the tree after adding DBRef field

        Return boolean indicating success
        '''
        assert hasattr(path, '__iter__')
        assert elita.util.type_check.is_string(collection)
        assert id.__class__.__name__ == 'ObjectId'
        assert util.type_check.is_optional_dict(doc)
        path_dot_notation = '.'.join(path)
        root_tree_doc = doc if doc else {}
        root_tree_doc['_doc'] = bson.DBRef(collection, id)
        result = self.db['root_tree'].update({}, {'$set': {path_dot_notation: root_tree_doc}}, fsync=True)
        return result['n'] == 1 and result['updatedExisting'] and not result['err']

    def rm_roottree(self, path):
        '''
        Delete/remove the root_tree reference at path
        '''
        assert hasattr(path, '__iter__')
        assert path
        path_dot_notation = '.'.join(path)
        result = self.db['root_tree'].update({}, {'$unset': {path_dot_notation: ''}}, fsync=True)
        return result['n'] == 1 and result['updatedExisting'] and not result['err']

    def get(self, collection, keys, multi=False, empty=False):
        '''
        Thin wrapper around find()
        Retrieve a document from Mongo, keyed by name. Optionally, if duplicates are found, delete all but the first.
        If empty, it's ok to return None if nothing matches

        Returns document
        @rtype: dict | list(dict) | None
        '''
        assert elita.util.type_check.is_string(collection)
        assert isinstance(keys, dict)
        assert collection
        dlist = [d for d in self.db[collection].find(keys)]
        assert dlist or empty
        if len(dlist) > 1 and not multi:
            logging.warning("Found duplicate entries ({}) for query {} in collection {}; dropping all but the first"
                            .format(len(dlist), keys, collection))
            keys['_id'] = {'$ne': dlist[0]['_id']}
            self.db[collection].remove(keys)
        return dlist if multi else (dlist[0] if dlist else dlist)

    def dereference(self, dbref):
        '''
        Simple wrapper around db.dereference()
        Returns document pointed to by DBRef

        @type id: bson.DBRef
        '''
        assert dbref
        assert dbref.__class__.__name__ == 'DBRef'
        return self.db.dereference(dbref)


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
        assert util.type_check.is_dictlike(dependency_objs)
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

        buildobj = Build({
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
        Update build with keys in doc.
        '''
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(name)
        assert isinstance(doc, dict)
        assert app and name
        assert app in self.root['app']
        assert name in self.root['app'][app]['builds']

        self.UpdateObject('builds', {'app_name': app, 'build_name': name}, doc)

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

        userobj = User({
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

        token = Token({
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
        assert elita.util.type_check.is_dictlike(doc)
        assert name in self.root['global']['users']

        if "password" in doc:
            user = User(doc)
            doc['hashed_pw'] = user.hashed_pw
            doc['salt'] = user.salt
            doc['password'] = None

        self.UpdateObject('users', {'username': name}, doc)


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
        assert elita.util.type_check.is_dictlike(doc)
        assert app in self.root['app']

        self.UpdateObject('applications', {'app_name': app}, doc)

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
        pm = PackageMap({
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
        assert elita.util.type_check.is_dictlike(doc)
        assert app in self.root['app']
        assert name in self.root['app'][app]['packagemaps']

        self.UpdateObject('packagemaps', {'application': app, 'name': name}, doc)

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
        gp = Group({
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
        assert elita.util.type_check.is_dictlike(doc)
        assert app in self.root['app']
        assert name in self.root['app'][app]['groups']

        self.UpdateObject('groups', {'application': app, 'name': name}, doc)

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
        job = Job({
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
            self.root['app'][app_name]['actions'][action_name] = Action(app_name, action_name, params, self)
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
        server = Server({
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
        assert elita.util.type_check.is_dictlike(doc)
        assert name in self.root['server']
        prototype = Server({})  # get all valid default top-level properties
        assert all([key in prototype.get_doc() for key in doc])

        self.UpdateObject('servers', {'name': name}, doc)

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
        gd_obj = GitDeploy({})
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
            util.change_dict_keys(actions, '.', EMBEDDED_YAML_DOT_REPLACEMENT)
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
        assert elita.util.type_check.is_dictlike(doc)
        assert app in self.root['app']
        assert name in self.root['app'][app]['gitdeploys']

        #clean up any actions
        if 'actions' in doc:
            util.change_dict_keys(doc['actions'], '.', EMBEDDED_YAML_DOT_REPLACEMENT)

        #replace gitrepo with DBRef if necessary
        if 'location' in doc and 'gitrepo' in doc['location']:
            grd = self.mongo_service.get('gitrepos', {'name': doc['location']['gitrepo'], 'application': app})
            assert grd
            doc['location']['gitrepo'] = bson.DBRef('gitrepos', grd['_id'])

        self.UpdateObject('gitdeploys', {'name': name, 'application': app}, doc)

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

        gpo = GitProvider({
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
        assert elita.util.type_check.is_dictlike(doc)
        assert name in self.root['global']['gitproviders']

        self.UpdateObject('gitproviders', {'name': name}, doc)

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

        gro = GitRepo({
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
        assert elita.util.type_check.is_dictlike(doc)
        assert app in self.root['app']

        self.UpdateObject('gitrepos', {'name': name, 'application': app}, doc)

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
    def NewDeployment(self, app, build_name, environments, groups, servers, gitdeploys, options):
        '''
        Create new deployment object

        @rtype: dict
        '''
        assert app and build_name and options and ((environments and groups) or (servers and gitdeploys))
        assert elita.util.type_check.is_string(app)
        assert elita.util.type_check.is_string(build_name)
        assert elita.util.type_check.is_dictlike(options)
        assert app in self.root['app']
        assert build_name in self.root['app'][app]['builds']
        assert all([not p for p in (environments, groups)]) or all([elita.util.type_check.is_seq(p) for p in (environments, groups)])
        assert all([not p for p in (servers, gitdeploys)]) or all([elita.util.type_check.is_seq(p) for p in (servers, gitdeploys)])
        assert not environments or set(environments).issubset(set(self.deps['ServerDataService'].GetEnvironments()))
        assert not groups or all([g in self.root['app'][app]['groups'] for g in groups])
        assert not servers or all([s in self.root['server'] for s in servers])
        assert not gitdeploys or all([gd in self.root['app'][app]['gitdeploys'] for gd in gitdeploys])


        dpo = Deployment({
            'name': "",
            'application': app,
            'build_name': build_name,
            'environments': environments,
            'groups': groups,
            'servers': servers,
            'gitdeploys': gitdeploys,
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
        assert elita.util.type_check.is_dictlike(doc)
        assert app in self.root['app']
        assert name in self.root['app'][app]['deployments']
        
        self.UpdateObject('deployments', {'application': app, 'name': name}, doc)

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
            kp_obj = KeyPair({
                "name": name,
                "attributes": attribs,
                "key_type": key_type,
                "private_key": private_key,
                "public_key": public_key
            })
        except:
            exc_type, exc_obj, tb = sys.exc_info()
            logging.debug("exception: {}, {}".format(exc_type, exc_obj))
            if exc_type == elita_exceptions.InvalidPrivateKey:
                err = "Invalid private key"
            if exc_type == elita_exceptions.InvalidPublicKey:
                err = "Invalid public key"
            if exc_type == elita_exceptions.InvalidKeyPairType:
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
        assert elita.util.type_check.is_dictlike(doc)
        assert name in self.root['global']['keypairs']

        self.UpdateObject('keypairs', {'name': name}, doc)

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

class SupportedFileType:
    TarGz = 'tar.gz'
    TarBz2 = 'tar.bz2'
    Zip = 'zip'
    types = [TarBz2, TarGz, Zip]


class GenericDataModel:
    __metaclass__ = elita.util.LoggingMetaClass

    default_values = {}

    def __init__(self, doc):
        self.set_defaults()
        if doc is not None:
            for k in doc:
                if k == '_id':
                    self.created_datetime = doc['_id'].generation_time
                elif k[0] != '_':
                    self.set_data(k, doc[k])
        self.init_hook()

    def init_hook(self):
        pass

    def set_defaults(self):
        for k in self.default_values:
            if not hasattr(self, k):
                setattr(self, k, self.default_values[k])

    def set_data(self, key, value):
        self._set_data(key, value)

    def _set_data(self, key, value):
        setattr(self, key, value)

    def update_values(self, doc):
        for k in doc:
            if hasattr(self, k):
                setattr(self, k, doc[k])

    def get_doc(self):
        return {k: getattr(self, k) for k in self.default_values}


class KeyPair(GenericDataModel):
    default_values = {
        "name": None,
        "attributes": dict(),
        "key_type": None,  # git | salt
        "private_key": None,
        "public_key": None
    }

    def init_hook(self):
        if self.key_type not in ("git", "salt"):
            raise elita_exceptions.InvalidKeyPairType
        kp = keypair.KeyPair(self.private_key, self.public_key)
        try:
            kp.verify_public()
        except:
            raise elita_exceptions.InvalidPublicKey
        try:
            kp.verify_private()
        except:
            raise elita_exceptions.InvalidPrivateKey

class Server(GenericDataModel):
    default_values = {
        "name": None,
        "server_type": None,
        "status": None,
        "environment": None,
        "attributes": dict(),
        "gitdeploys": [bson.DBRef("", None)],
        "salt_key": bson.DBRef("", None)
    }

class Environment(GenericDataModel):
    default_values = {
        "environments": None
    }

class GitProvider(GenericDataModel):
    default_values = {
        'name': None,
        'type': None,
        'auth': {
            'username': None,
            'password': None
        }
    }

class GitRepo(GenericDataModel):
    default_values = {
        'name': None,
        'application': None,
        'last_build': None,
        'uri': None,
        'keypair': bson.DBRef("", None),
        'gitprovider': bson.DBRef("", None)
    }

class GitDeploy(GenericDataModel):
    default_values = {
        'name': None,
        'application': None,
        'package': 'master',
        'servers': list(),
        'attributes': dict(),
        'deployed_build': None,
        'options': {
            'favor': 'ours',
            'ignore-whitespace': 'true',
            'gitignore': list()
        },
        'actions': {
            'prepull': [],
            'postpull': []
        },
        'location': {
            'path': None,
            'git_repo': bson.DBRef("", None),
            'default_branch': None,
            'current_branch': None,
            'current_rev': None
        }
    }

class Deployment(GenericDataModel):
    '''
    There are two "phases" to a deployment:
        - Phase 1: processing of gitdeploys (applying packages, adding/committing/pushing to gitprovider, determining
            changes)
        - Phase 2: Performing salt states/git pull on target machines. Can be broken up into an arbitrary number of
            batches
    '''
    default_values = {
        'name': None,  # "name" for consistency w/ other models, even though it's really id
        'application': None,
        'build_name': None,
        'environments': None,
        'groups': None,
        'servers': None,
        'gitdeploys': None,
        'options': dict(),  # pauses, divisor
        'status': None,
        'commits': dict(),    # { gitrepo_name: commit_hash }
        'progress': {
            'currently_on': None,
            'phase1': {
                'gitrepos': dict()
            },
            'phase2': dict()
        },
        'job_id': None
    }

class Build(GenericDataModel):
    default_values = {
        'build_name': None,
        'app_name': None,
        'files': list(),
        'stored': False,
        'master_file': None,
        'packages': dict(),
        'attributes': dict()
    }


class Action:
    def __init__(self, app_name, action_name, params, job_datasvc):
        self.app_name = app_name
        self.action_name = action_name
        self.params = params
        self.job_datasvc = job_datasvc

    def execute(self, params):
        return self.job_datasvc.ExecuteAction(self.app_name, self.action_name, params)

    def details(self):
        return self.job_datasvc.GetAction(self.app_name, self.action_name)

class Application(GenericDataModel):
    default_values = {
        'app_name': None
    }

DEFAULT_ADMIN_USERNAME = 'admin'
DEFAULT_ADMIN_PASSWORD = 'elita'
DEFAULT_ADMIN_PERMISSIONS = {
    'apps': {
        '*': 'read/write',
        '_global': 'read/write'
    },
    'actions': {
        '*': {
            '*': 'execute'
        }
    },
    'servers': ['*']
}

class User(GenericDataModel):
    default_values = {
        'username': None,
        'password': None,
        'hashed_pw': None,
        'salt': None,
        'attributes': dict(),
        'permissions': {
            'apps': {},
            'actions': {},
            'servers': []
        }
    }

    def init_hook(self):
        assert self.hashed_pw or self.password
        if self.password:   # new or changed password
            self.salt = base64.urlsafe_b64encode(uuid.uuid4().bytes)
            self.hashed_pw = self.hash_pw(self.password)
            self.password = None

    def hash_pw(self, pw):
        assert pw is not None
        return base64.urlsafe_b64encode(hashlib.sha512(pw + self.salt).hexdigest())

    def validate_password(self, pw):
        return self.hashed_pw == self.hash_pw(pw)


#dummy model. Values are computed for each request
class UserPermissions(GenericDataModel):
    default_values = {
        'username': None,
        'applications': None,
        'actions': None,
        'servers': None
    }

class Token(GenericDataModel):
    default_values = {
        'username': None,
        'token': None
    }

    def init_hook(self):
        self.token = base64.urlsafe_b64encode(hashlib.sha256(uuid.uuid4().bytes).hexdigest())[:-2] \
            if self.token is None else self.token

class Job(GenericDataModel):
    default_values = {
        'status': 'running',
        'name': None,
        'job_type': None,
        'data': None,
        'completed_datetime': None,
        'duration_in_seconds': None,
        'attributes': None,
        'job_id': None
    }

    def init_hook(self):
        self.job_id = uuid.uuid4() if self.job_id is None else self.job_id

class Group(GenericDataModel):
    default_values = {
        'application': None,
        'name': None,
        'description': None,
        'gitdeploys': list(),
        'attributes': dict(),
        'rolling_deploy': False
    }

class PackageMap(GenericDataModel):
    default_values = {
        'application': None,
        'name': None,
        'attributes': dict(),
        'packages': dict()
    }
    # Example packages field:
    # packages = {
    #     'package_name': [{
    #             'patterns': ["foo/bar/*"],
    #             'prefix': "foobar/",
    #             'remove_prefix': "bar/"
    #     }]
    # }

class GenericContainer:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, doc):
        self.name = doc['name']
        self.parent = doc['parent']
        self.created_datetime = doc['_id'].generation_time if '_id' in doc else None


class BuildContainer(GenericContainer):
    pass

class ActionContainer(GenericContainer):
    pass

class UserContainer(GenericContainer):
    pass

class TokenContainer(GenericContainer):
    pass

class ApplicationContainer(GenericContainer):
    pass

class GlobalContainer(GenericContainer):
    pass

class JobContainer(GenericContainer):
    pass

class ServerContainer(GenericContainer):
    pass

class GitProviderContainer(GenericContainer):
    pass

class GitRepoContainer(GenericContainer):
    pass

class GitDeployContainer(GenericContainer):
    pass

class DeploymentContainer(GenericContainer):
    pass

class KeyPairContainer(GenericContainer):
    pass

class GroupContainer(GenericContainer):
    pass

class PackageMapContainer(GenericContainer):
    pass

class Root(GenericContainer):
    pass

class RootTree(collections.MutableMapping):

    def __init__(self, db, updater, tree, doc, *args, **kwargs):
        self.pp = pprint.PrettyPrinter(indent=4)
        self.db = db
        self.tree = tree
        self.doc = doc
        self.updater = updater

    def is_action(self):
        return self.doc and self.doc['_class'] == 'ActionContainer'

    def __getitem__(self, key):
        key = self.__keytransform__(key)
        if self.is_action():
            return self.tree[key]
        if key in self.tree:
            if key == '_doc':
                return self.tree[key]
            doc = self.db.dereference(self.tree[key]['_doc'])
            if doc is None:
                logging.debug("RootTree: __getitem__: {}: doc is None: KeyError".format(key))
                raise KeyError
            return RootTree(self.db, self.updater, self.tree[key], doc)
        else:
            logging.debug("RootTree: __getitem__: {}: key not in self.tree: KeyError".format(key))
            raise KeyError

    def __setitem__(self, key, value):
        self.tree[key] = value
        if not self.is_action():     # dynamically populated each request
            pass
            #self.updater.update()

    def __delitem__(self, key):
        del self.tree[key]
        #self.updater.update()
        return

    def __iter__(self):
        return iter(self.tree)

    def __len__(self):
        return len(self.tree)

    def __keytransform__(self, key):
        return key

class RootTreeUpdater:

    def __init__(self, tree, db):
        self.tree = tree
        self.db = db

    def clean_actions(self):
        #actions can't be serialized into mongo
        for a in self.tree['app']:
            actions = list()
            if a[0] != '_':
                if "actions" in self.tree['app'][a]:
                    for ac in self.tree['app'][a]['actions']:
                        if ac[0] != '_':
                            actions.append(ac)
                    for action in actions:
                        del self.tree['app'][a]['actions'][action]

    def update(self):
        self.clean_actions()
        root_tree = self.db['root_tree'].find_one()
        self.db['root_tree'].update({"_id": root_tree['_id']}, self.tree)

class DataValidator:
    '''
    Responsible for:
        - Creating proper data model/root_tree on first run
        - Validating that data isn't broken/inconsistent
        - Running migrations between versions
    '''
    __metaclass__ = util.LoggingMetaClass

    def __init__(self, settings, root, db):
        '''
        @type settings: pyramid.registry.Registry
        @type root: dict
        @type db: pymongo.database.Database
        '''
        # root is optional if this is the first time elita runs
        assert settings and db
        self.settings = settings
        self.root = root
        self.db = db

    def run(self):
        # order is very significant
        logging.debug("running")
        self.check_root()
        self.check_toplevel()
        self.check_global()
        self.check_root_references()
        self.check_users()
        self.check_user_permissions()
        self.check_doc_consistency()
        self.check_containers()
        self.check_apps()
        self.check_jobs()
        self.check_deployments()
        self.check_servers()
        self.check_gitdeploys()
        self.check_gitrepos()
        self.check_groups()
        self.SaveRoot()

    def SaveRoot(self):
        logging.debug('saving root_tree')
        self.db['root_tree'].save(self.root)

    def NewContainer(self, class_name, name, parent):
        cdoc = self.db['containers'].insert({'_class': class_name,
                                         'name': name,
                                         'parent': parent})
        return bson.DBRef('containers', cdoc)

    def check_doc_consistency(self):
        #enforce collection rules and verify connectivity b/w objects and root tree
        collects = [
            'applications',
            'builds',
            'gitproviders',
            'gitrepos',
            'gitdeploys',
            'jobs',
            'tokens',
            'users',
            'servers',
            'groups',
            'packagemaps'
        ]
        for c in collects:
            rm_docs = list()
            for d in self.db[c].find():
                if '_class' not in d:
                    logging.warning("class specification not found in object {} from collection {}"
                    .format(d['_id'], c))
                    logging.debug("...deleting malformed object")
                    self.db[c].remove({'_id': d['_id']})
                if c == 'applications':
                    if d['app_name'] not in self.root['app']:
                        logging.warning("orphan application object: '{}', adding to root tree".format(d['app_name']))
                        self.root['app'][d['app_name']] = {'_doc': bson.DBRef('applications', d['_id'])}
                    if self.root['app'][d['app_name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked application document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'builds':
                    if d['build_name'] not in self.root['app'][d['app_name']]['builds']:
                        logging.warning("orphan build object: '{}/{}', adding to root tree".format(d['app_name'], d['build_name']))
                        self.root['app'][d['app_name']]['builds'][d['build_name']] = {'_doc': bson.DBRef('builds', d['_id'])}
                    if self.root['app'][d['app_name']]['builds'][d['build_name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked build document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'gitproviders':
                    if d['name'] not in self.root['global']['gitproviders']:
                        logging.warning("orphan gitprovider object: '{}', adding to root tree".format(d['name']))
                        self.root['global']['gitproviders'][d['name']] = {'_doc': bson.DBRef('gitproviders', d['_id'])}
                    if self.root['global']['gitproviders'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked gitprovider document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'gitrepos':
                    if d['name'] not in self.root['app'][d['application']]['gitrepos']:
                        logging.warning("orphan gitrepo object: '{}/{}', adding to root tree".format(d['application'], d['name']))
                        self.root['app'][d['application']]['gitrepos'][d['name']] = {'_doc': bson.DBRef('gitrepos', d['_id'])}
                    if self.root['app'][d['application']]['gitrepos'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked gitrepo document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'gitdeploys':
                    if d['name'] not in self.root['app'][d['application']]['gitdeploys']:
                        logging.warning("orphan gitdeploy object: '{}/{}', adding to root tree".format(d['application'], d['name']))
                        self.root['app'][d['application']]['gitdeploys'][d['name']] = {'_doc': bson.DBRef('gitdeploys', d['_id'])}
                    if self.root['app'][d['application']]['gitdeploys'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked gitdeploy document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'jobs':
                    if d['job_id'] not in self.root['job']:
                        logging.warning("orphan job object: '{}', adding to root tree".format(d['job_id']))
                        self.root['job'][d['job_id']] = {'_doc': bson.DBRef('jobs', d['_id'])}
                    #we don't really care about unlinked jobs
                if c == 'tokens':
                    if d['token'] not in self.root['global']['tokens']:
                        logging.warning("orphan token object: '{}', adding to root tree".format(d['token']))
                        self.root['global']['tokens'][d['token']] = {'_doc': bson.DBRef('tokens', d['_id'])}
                    if self.root['global']['tokens'][d['token']]['_doc'].id != d['_id']:
                        logging.warning("unlinked token document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'users':
                    if d['username'] not in self.root['global']['users']:
                        logging.warning("orphan user object: '{}', adding to root tree".format(d['username']))
                        self.root['global']['users'][d['username']] = {'_doc': bson.DBRef('users', d['_id'])}
                    if self.root['global']['users'][d['username']]['_doc'].id != d['_id']:
                        logging.warning("unlinked user document found ({}), deleting".format(d['username']))
                        rm_docs.append(d['_id'])
                if c == 'servers':
                    if d['name'] not in self.root['server']:
                        logging.warning("orphan server object: '{}', adding to root tree".format(d['name']))
                        self.root['server'][d['name']] = {'_doc': bson.DBRef('servers', d['_id'])}
                    if self.root['server'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked server document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'groups':
                    if d['name'] not in self.root['app'][d['application']]['groups']:
                        logging.warning("orphan group object: '{}', adding to root tree".format(d['name']))
                        self.root['app'][d['application']]['groups'][d['name']] = {'_doc': bson.DBRef('groups', d['_id'])}
                    if self.root['app'][d['application']]['groups'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked group document found ({}), deleting".format(d['name']))
                        rm_docs.append(d['_id'])
                if c == 'packagemaps':
                    if d['name'] not in self.root['app'][d['application']]['packagemaps']:
                        logging.warning("orphan packagemap object: '{}', adding to root tree".format(d['name']))
                        self.root['app'][d['application']]['packagemaps'][d['name']] = {'_doc': bson.DBRef('packagemaps', d['_id'])}
                    if self.root['app'][d['application']]['packagemaps'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked packagemap document found ({}), deleting".format(d['name']))
                        rm_docs.append(d['_id'])
            for id in rm_docs:
                self.db[c].remove({'_id': id})

    @staticmethod
    def check_root_refs(db, obj):
        '''
        Recurse into obj, find DBRefs, check if they are valid
        '''
        for k in obj:
            if k == '_doc':
                if not db.dereference(obj[k]):
                    logging.warning("Invalid dbref found! {}".format(obj[k].collection))
            elif k[0] != '_' and not isinstance(obj[k], bson.ObjectId):
                DataValidator.check_root_refs(db, obj[k])

    def check_root_references(self):
        '''
        Check that every DBRef in the root tree points to a valid document
        '''
        DataValidator.check_root_refs(self.db, self.root)

    def check_global(self):
        global_levels = {
            'users': {
                'class': "UserContainer"
            },
            'tokens': {
                'class': "TokenContainer"
            },
            'gitproviders': {
                'class': "GitProviderContainer"
            },
            'keypairs': {
                'class': "KeyPairContainer"
            }
        }
        for l in global_levels:
            if l not in self.root['global']:
                logging.warning("'{}' not found under global".format(l))
                self.root['global'][l] = dict()
                self.root['global'][l]['_doc'] = self.NewContainer(global_levels[l]['class'], l, "")
        if DEFAULT_ADMIN_USERNAME not in self.root['global']['users']:
            logging.warning("admin user not found")
            users = [u for u in self.db['users'].find()]
            if DEFAULT_ADMIN_USERNAME in [u['username'] for u in users]:
                admin = self.db['users'].find_one({'username': DEFAULT_ADMIN_USERNAME})
                assert admin
                self.root['global']['users'][DEFAULT_ADMIN_USERNAME] = {
                    '_doc': bson.DBRef('users', admin['_id'])
                }

    def check_users(self):
        for u in self.root['global']['users']:
            if u != '_doc':
                if "permissions" not in self.root['global']['users'][u]:
                    logging.warning("permissions container object not found under user {} in root tree; "
                                        "fixing".format(u))
                    pid = self.db['userpermissions'].insert({
                            "_class": "UserPermissions",
                            "username": u,
                            "applications": list(),
                            "actions": dict(),
                            "servers": list()
                    })
                    self.root['global']['users'][u]['permissions'] = {
                        '_doc': bson.DBRef('userpermissions', pid)
                    }
        users = [u for u in self.db['users'].find()]
        for u in users:
            if 'username' not in u:
                logging.warning("user found without username property; fixing {}".format(u['_id']))
                if 'name' in u:
                    u['username'] = u['name']
                    self.db['users'].save(u)
                else:
                    logging.warning("...couldn't fix user because name field not found!")
        if DEFAULT_ADMIN_USERNAME not in [u['username'] for u in users]:
            logging.warning("admin user document not found; creating")
            userobj = User({
                'username': DEFAULT_ADMIN_USERNAME,
                'permissions': DEFAULT_ADMIN_PERMISSIONS,
                'password': DEFAULT_ADMIN_PASSWORD
            })
            doc = userobj.get_doc()
            doc['_class'] = 'User'
            uid = self.db['users'].insert(doc)
            pid = self.db['userpermissions'].insert({
                "_class": "UserPermissions",
                "username": DEFAULT_ADMIN_USERNAME,
                "applications": list(),
                "actions": dict(),
                "servers": list()
            })
            self.root['global']['users'][DEFAULT_ADMIN_USERNAME] = {
                '_doc': bson.DBRef('users', uid),
                'permissions': {
                    '_doc': bson.DBRef('userpermissions', pid)
                }
            }

    def check_user_permissions(self):
        for u in self.db['users'].find():
            if 'permissions' not in u:
                logging.warning("permissions object not found for user {}; fixing with empty obj"
                              .format(u['username']))
                u['permissions'] = {
                    'apps': {},
                    'actions': {},
                    'servers': []
                }
            for o in ('apps', 'actions', 'servers'):
                if o not in u['permissions']:
                    logging.warning("{} not found in permissions object for user {}; fixing with empty "
                                        "obj".format(o, u['username']))
                    u['permissions'][o] = list() if o == 'servers' else dict()
            if not isinstance(u['permissions']['servers'], list):
                logging.warning("servers key under permissions object for user {} is not a list; fixing"
                              .format(u['username']))
                u['permissions']['servers'] = list(u['permissions']['servers'])
            for o in ('apps', 'actions'):
                if not isinstance(u['permissions'][o], dict):
                    logging.warning("{} key under permissions object for user {} is not a dict; invalid "
                                        "so replacing with empty dict".format(o, u['username']))
                    u['permissions'][o] = dict()
            self.db['users'].save(u)

    def check_jobs(self):
        djs = list()
        for j in self.root['job']:
            if j[0] != '_':
                if self.db.dereference(self.root['job'][j]['_doc']) is None:
                    logging.warning("found dangling job ref in root tree: {}; deleting".format(j))
                    djs.append(j)
        for j in djs:
            del self.root['job'][j]
        job_fixlist = list()
        for doc in self.db['jobs'].find():
            if doc['job_id'] not in self.root['job']:
                job_id = doc['job_id']
                logging.warning("found orphan job: {}; adding to root tree".format(doc['job_id']))
                self.root['job'][job_id] = {'_doc': bson.DBRef('jobs', doc['_id'])}
            for k in ('job_type', 'data', 'name'):
                if k not in doc:
                    logging.warning("found job without {}: {}; adding blank".format(k, doc['job_id']))
                    doc[k] = ""
                    job_fixlist.append(doc)
        for d in job_fixlist:
            self.db['jobs'].save(d)

    def check_apps(self):
        app_sublevels = {
            'builds': {
                'class': "BuildContainer"
            },
            'actions': {
                'class': "ActionContainer"
            },
            'gitrepos': {
                'class': "GitRepoContainer"
            },
            'gitdeploys': {
                'class': "GitDeployContainer"
            },
            'deployments': {
                'class': "DeploymentContainer"
            },
            'groups': {
                'class': "GroupContainer"
            },
            'packagemaps': {
                'class': "PackageMapContainer"
            }
        }
        for a in self.root['app']:
            if a[0] != '_':
                if 'action' in self.root['app'][a]:
                    logging.warning("found old 'action' container under app {}; deleting".format(a))
                    del self.root['app'][a]['action']
                for sl in app_sublevels:
                    if sl not in self.root['app'][a]:
                        logging.warning("'{}' not found under {}".format(sl, a))
                        self.root['app'][a][sl] = dict()
                        self.root['app'][a][sl]['_doc'] = self.NewContainer(app_sublevels[sl]['class'], sl, a)
                    d_o = list()
                    for o in self.root['app'][a][sl]:
                        if o[0] != '_' and '_doc' in self.root['app'][a][sl][o]:
                            if self.db.dereference(self.root['app'][a][sl][o]['_doc']) is None:
                                logging.warning("dangling {} reference '{}' in app {}; deleting".format(sl, o, a))
                                d_o.append(o)
                    for d in d_o:
                        del self.root['app'][a][sl][d]

    def check_servers(self):
        ds = list()
        for s in self.root['server']:
            if s[0] != '_':
                if self.db.dereference(self.root['server'][s]['_doc']) is None:
                    logging.warning("found dangling server ref in root tree: {}; deleting".format(s))
                    ds.append(s)
        for s in ds:
            del self.root['server'][s]
        update_list = list()
        for d in self.db['servers'].find():
            update = False
            if 'environment' not in d:
                logging.warning("environment field not found for server {}; fixing".format(d['_id']))
                d['environment'] = ""
                update = True
            if 'status' not in d:
                logging.warning("status field not found for server {}; fixing".format(d['_id']))
                d['status'] = "ok"
                update = True
            if update:
                update_list.append(d)
        for d in update_list:
            self.db['servers'].save(d)

    def check_deployments(self):
        update_list = list()
        for d in self.db['deployments'].find():
            if 'server_specs' in d:
                logging.warning("found deployment with old-style server_specs object: {}; fixing".format(
                    d['_id']))
                d['deployment'] = {
                    'servers': d['server_specs']['spec'],
                    'gitdeploys': d['server_specs']['gitdeploys']
                }
                update_list.append(d)
            if 'job_id' not in d:
                logging.warning("found deployment without job_id: {}; fixing with blank job".format(d[
                    '_id']))
                d['job_id'] = ""
                update_list.append(d)
            if 'results' in d:
                logging.warning("found deployment with old-style results field: {}; removing"
                              .format(d['_id']))
                update_list.append(d)
            if 'status' not in d:
                logging.warning("found deployment without status: {}; fixing with blank".format(d['_id']))
                d['status'] = ""
                update_list.append(d)
            if 'progress' not in d:
                logging.warning("found deployment without progress: {}; fixing with empty dict".format(d['_id']))
                d['progress'] = dict()
                update_list.append(d)
        for d in update_list:
            if 'server_specs' in d:
                del d['server_specs']
            if 'results' in d:
                del d['results']
            self.db['deployments'].save(d)

        update_list = list()
        for a in self.root['app']:
            if a[0] != '_':
                for d in self.root['app'][a]['deployments']:
                    if d[0] != '_':
                        doc = self.db.dereference(self.root['app'][a]['deployments'][d]['_doc'])
                        assert doc is not None
                        if 'name' not in doc:
                            logging.warning("name not found under deployment {}; fixing".format(d))
                            doc['name'] = d
                            update_list.append(doc)
        if len(update_list) > 0:
            for d in update_list:
                self.db['deployments'].save(d)

    def check_gitdeploys(self):
        dlist = list()
        fixlist = list()
        for d in self.db['gitdeploys'].find():
            delete = False
            for k in ('application', 'name', 'package', 'location'):
                if k not in d:
                    logging.warning("mandatory key '{}' not found under gitdeploy {}; removing".
                                  format(k, d['_id']))
                    dlist.append(d['_id'])
                    delete = True
            fix = False
            if 'attributes' not in d and not delete:
                logging.warning("attributes not found under gitdeploy {}; fixing".format(d['_id']))
                d['attributes'] = dict()
                fix = True
            if 'actions' not in d and not delete:
                logging.warning("actions not found under gitdeploy {}; fixing".format(d['_id']))
                d['actions'] = {
                    'prepull': dict(),
                    'postpull': dict()
                }
                fix = True
            if 'servers' not in d and not delete:
                logging.warning("servers not found under gitdeploy {}; fixing".format(d['_id']))
                d['servers'] = list()
                fix = True
            if 'server' in d:
                logging.warning("gitdeploy found with obsolete server field {}; removing".format(d['_id']))
                del d['server']
                fix = True
            if len([x for x, y in collections.Counter(d['servers']).items() if y > 1]) > 0 and not delete:
                logging.warning("duplicate server entries found in gitdeploy {}; fixing".format(d['_id']))
                d['servers'] = list(set(tuple(d['servers'])))
                fix = True
            if 'deployed_build' not in d:
                logging.warning("deployed_build not found in gitdeploy {}".format(d['_id']))
                gr_doc = self.db.dereference(d['location']['gitrepo'])
                if not gr_doc or 'last_build' not in gr_doc:
                    logging.debug("...ERROR: referenced gitrepo not found! Aborting fix...")
                else:
                    d['deployed_build'] = gr_doc['last_build']
                    fix = True
            if fix:
                fixlist.append(d)
        for f in fixlist:
            self.db['gitdeploys'].find_and_modify(query={'_id': f['_id']}, update=f, upsert=True,
                                                  new=True)
        for dl in dlist:
            self.db['gitdeploys'].remove({'_id': dl})

    def check_gitrepos(self):
        fixlist = list()
        for d in self.db['gitrepos'].find():
            if 'uri' in d:
                if d['uri'] is not None and ':' in d['uri']:
                    logging.warning("found gitrepo URI with ':'; replacing with '/' ({})".format(d['name']))
                    d['uri'] = d['uri'].replace(':', '/')
                    fixlist.append(d)
            else:
                logging.warning("found gitrepo without URI ({}); adding empty field".format(d['name']))
                d['uri'] = ""
                fixlist.append(d)
            if 'last_build' not in d:
                logging.warning("found gitrepo without last_build: {}; adding empty field".format(d['name']))
                d['last_build'] = None
                fixlist.append(d)
        for d in fixlist:
            self.db['gitrepos'].save(d)

    def check_groups(self):
        fixlist = list()
        for d in self.db['groups'].find():
            fix = False
            if 'description' not in d:
                logging.warning("found group without description: {}; fixing".format(d['name']))
                d['description'] = None
                fix = True
            if 'servers' in d:
                logging.warning("found group with explicit server list: {}; removing".format(d['name']))
                del d['servers']
                fix = True
            if 'rolling_deploy' not in d:
                logging.warning("found group without rolling_deploy flag: {}; fixing".format(d['name']))
                d['rolling_deploy'] = False
                fix = True
            if fix:
                fixlist.append(d)
        for d in fixlist:
            self.db['groups'].save(d)

    def check_toplevel(self):
        top_levels = {
            'app': {
                'class': "ApplicationContainer"
            },
            'global': {
                'class': "GlobalContainer"
            },
            'job': {
                'class': 'JobContainer'
            },
            'server': {
                'class': 'ServerContainer'
            }
        }
        for tl in top_levels:
            if tl not in self.root:
                logging.warning("'{}' not found under root".format(tl))
                self.root[tl] = dict()
                self.root[tl]['_doc'] = self.NewContainer(top_levels[tl]['class'], tl, "")
            if tl == 'server':
                if "environments" not in self.root[tl] or isinstance(self.root[tl]['environments'], bson.DBRef):
                    logging.warning("environments endpoint not found under servers container; fixing")
                    eid = self.db['environments'].insert({
                        '_class': "Environment",
                        'environments': ""
                    })
                    self.root[tl]['environments'] = {
                        "_doc": bson.DBRef("environments", eid)
                    }

    def check_containers(self):
        update_list = list()
        for c in self.db['containers'].find():
            if c['_class'] == 'AppContainer':
                logging.warning("found Application container with incorrect 'AppContainer' class; fixing")
                c['_class'] = 'ApplicationContainer'
                update_list.append(c)
        for c in update_list:
            self.db['containers'].save(c)

    def check_root(self):
        if not self.root:
            logging.warning("no root_tree found!")
        self.root = dict() if not self.root else self.root
        if '_class' in self.root:
            logging.warning("'_class' found in base of root; deleting")
            del self.root['_class']
        if '_doc' not in self.root:
            logging.warning("'_doc' not found in base of root")
            self.root['_doc'] = self.NewContainer('Root', 'Root', '')
        rt_list = [d for d in self.db['root_tree'].find()]
        if len(rt_list) > 1:
            logging.warning("duplicate root_tree docs found! Removing all but the first")
            for d in rt_list[1:]:
                self.db['root_tree'].remove({'_id': d['_id']})


