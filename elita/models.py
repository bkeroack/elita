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
import pymongo
import pyramid.registry
import random
import time

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
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, db, timeout=30):
        self.db = db

    def create_new(self, collection, keys, classname, doc, remove_existing=True):
        '''
        Creates new document in collection. Optionally, remove any existing according to keys (which specify how the
        new document is unique)

        Returns id of new document
        '''
        assert isinstance(collection, str)
        assert isinstance(keys, dict)
        assert isinstance(classname, str)
        assert isinstance(doc, dict)
        assert collection
        # keys/classname are only mandatory if remove_existing=True
        assert (keys and classname and remove_existing) or not remove_existing
        existing = None
        if remove_existing:
            existing = [d for d in self.db[collection].find(keys)]
            doc['_class'] = classname
            for k in keys:
                doc[k] = keys[k]
            if '_id' in doc:
                del doc['_id']
        id = self.db[collection].save(doc)
        if existing and remove_existing:
            self.db[collection].remove(keys, {'$not': {'_id': id}})
        return id

    def modify(self, collection, keys, path, doc_or_obj):
        '''
        Modifies document with the keys in doc. Does so atomically but remember that any key will overwrite the existing
        key.

        Returns boolean indicating success
        '''
        assert hasattr(path, '__iter__')
        assert path
        assert isinstance(collection, str)
        assert isinstance(keys, dict)
        assert collection and keys
        assert doc_or_obj
        dlist = [d for d in self.db[collection].find(keys)]
        assert dlist
        canonical_id = dlist[0]['_id']
        if len(dlist) > 1:
            logging.warning("Found duplicate entries for query {} in collection {}; using the first and removing others"
                            .format(keys, collection))
            self.db[collection].remove({'_id': {'$ne': canonical_id}})
        path_dot_notation = '.'.join(path)
        result = self.db[collection].update({'_id': canonical_id}, {'$set': {path_dot_notation: doc_or_obj}})
        return result['n'] == 1 and result['updatedExisting'] and not result['err']

    def delete(self, collection, keys):
        '''
        Drop a document from the collection

        Return whatever pymongo returns for deletion
        '''
        assert isinstance(collection, str)
        assert isinstance(keys, dict)
        assert collection and keys
        dlist = [d for d in self.db[collection].find(keys)]
        assert dlist
        if len(dlist) > 1:
            logging.warning("Found duplicate entries for query {} in collection {}; removing all".format(keys,
                                                                                                        collection))
        return self.db[collection].remove(keys)

    def update_roottree(self, path, collection, id, doc=None):
        '''
        Update the root tree at path [must be a tuple of indices: ('app', 'myapp', 'builds', '123-foo')] with DBRef
        Optional doc can be passed in which will be inserted into the tree after adding DBRef field

        Return boolean indicating success
        '''
        assert hasattr(path, '__iter__')
        assert isinstance(collection, str)
        assert id.__class__.__name__ == 'ObjectId'
        assert util.type_check.is_optional_dict(doc)
        path_dot_notation = '.'.join(path)
        root_tree_doc = doc if doc else {}
        root_tree_doc['_doc'] = bson.DBRef(collection, id)
        result = self.db['root_tree'].update({}, {'$set': {path_dot_notation: root_tree_doc}})
        return result['n'] == 1 and result['updatedExisting'] and not result['err']

    def rm_roottree(self, path):
        '''
        Delete/remove the root_tree reference at path
        '''
        assert hasattr(path, '__iter__')
        assert path
        path_dot_notation = '.'.join(path)
        result = self.db['root_tree'].update({}, {'$unset': {path_dot_notation: ''}})
        return result['n'] == 1 and result['updatedExisting'] and not result['err']

    def get(self, collection, keys, multi=False):
        '''
        Thin wrapper around find()
        Retrieve a document from Mongo, keyed by name. Optionally, if duplicates are found, delete all but the first.

        Returns document
        @rtype: dict | list(dict)
        '''
        assert isinstance(collection, str)
        assert isinstance(keys, dict)
        assert collection
        dlist = [d for d in self.db[collection].find(keys)]
        assert dlist
        if len(dlist) > 1 and not multi:
            logging.warning("Found duplicate entries for query {} in collection {}; dropping all but the first"
                            .format(keys, collection))
            self.db[collection].remove({'_id': {'$ne': dlist[0]['_id']}})
        return dlist if multi else dlist[0]

class GenericChildDataService:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, mongo_service, root, job_id=None):
        '''
        @type mongo_service: MongoService
        @type root: RootTree
        @type job_id: None | str
        '''
        assert isinstance(mongo_service, MongoService)
        assert isinstance(root, RootTree)
        assert elita.util.type_check.is_optional_str(job_id)
        self.mongo_service = mongo_service
        self.root = root
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
        assert isinstance(class_name, str)
        assert isinstance(name, str)
        assert isinstance(parent, str)
        return self.mongo_service.create_new('containers', {'name': name}, class_name, {'name': name, 'parent': parent})

class BuildDataService(GenericChildDataService):

    def GetBuilds(self, app_name):
        '''
        Get all builds for application.

        When getting a list of all objects of a given type, the convention is to pull from in-memory root_tree instead
        of directly from mongo. This keeps it fast so we can do it frequently for things like parameter validation, etc
        '''
        assert app_name
        assert isinstance(app_name, str)
        assert app_name in self.root['app']
        return [build for build in self.root['app'][app_name]['builds'] if build[0] != '_']

    def NewBuild(self, app_name, build_name, attribs):
        '''
        Create new build document
        '''
        assert isinstance(app_name, str)
        assert isinstance(build_name, str)
        assert isinstance(attribs, dict)
        assert app_name and build_name

        app_doc = self.mongo_service.get('application', {'name': app_name})
        assert app_doc
        build_doc = self.mongo_service.get('builds', {'app_name': app_name, 'build_name': build_name})
        assert not build_doc

        buildobj = Build({
            'app_name': app_name,
            'build_name': build_name,
            'attributes': attribs
        })
        new_doc = {
            'build_name': buildobj.build_name,
            'files': buildobj.files,
            'stored': buildobj.stored,
            'app_name': buildobj.app_name,
            'packages': buildobj.packages,
            'attributes': buildobj.attributes
        }
        res1 = self.parent.ms.create_new('builds', build_name, 'Builds', new_doc)
        res2 = self.parent.ms.update_roottree(('app', app_name, 'builds', build_name), 'builds', id)
        return res1 and res2

    def AddPackages(self, app, build, packages):
        '''
        Add new packages fields to existing build. Regenerate legacy 'files' field (which is a flat array of files
        associated with build
        '''

        assert isinstance(app, str)
        assert isinstance(build, str)
        assert isinstance(packages, dict)

        app_doc = self.mongo_service.get('application', {'name': app})
        assert app_doc
        build_doc = self.mongo_service.get('builds', {'app_name': app, 'build_name': build})
        assert build_doc

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
        Legacy method.

        Update build with keys in doc. Overwrite existing contents (ie, the document is not recursed into)
        '''
        assert isinstance(app, str)
        assert isinstance(name, str)
        assert isinstance(doc, dict)
        assert app and name

        app_doc = self.mongo_service.get('application', {'name': app})
        assert app_doc
        build_doc = self.mongo_service.get('builds', {'app_name': app, 'build_name': name})
        assert build_doc

        for k in doc:
            self.mongo_service.modify('builds', {'app_name': app, 'build_name': name}, (k,), doc[k])

    def DeleteBuildStorage(self, app_name, build_name):
        '''
        Delete all stored files associated with build.
        '''
        assert isinstance(app_name, str)
        assert isinstance(build_name, str)
        assert app_name and build_name

        app_doc = self.mongo_service.get('application', {'name': app_name})
        assert app_doc
        build_doc = self.mongo_service.get('builds', {'app_name': app_name, 'build_name': build_name})
        assert build_doc

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
        assert isinstance(app_name, str)
        assert isinstance(build_name, str)
        assert app_name and build_name

        root_path = ('app', app_name, 'builds', build_name)
        self.mongo_service.rm_roottree(root_path)
        self.mongo_service.delete('builds', {'app_name': app_name, 'build_name': build_name})
        self.DeleteBuildStorage(app_name, build_name)

    def GetBuild(self, app_name, build_name):
        '''
        Legacy API. Get build OBJECT (not document). Uses overly-clever method of letting RootTree class
        dereference the DBRef, rather than pulling from mongo directly.
        '''
        assert isinstance(app_name, str)
        assert isinstance(build_name, str)
        assert app_name and build_name
        return Build(self.root['app'][app_name]['builds'][build_name].doc)

    def GetBuildDoc(self, app_name, build_name):
        '''
        Legacy API to get document associated with build.
        '''
        assert isinstance(app_name, str)
        assert isinstance(build_name, str)
        assert app_name and build_name
        bobj = self.GetBuild(app_name, build_name)
        return bobj.get_doc()

class UserDataService(GenericChildDataService):

    def NewUser(self, name, pw, perms, attribs):
        '''
        Create a new user object and insert root_tree references for both the user and the computed permissions
        endpoint. Pipe parameters into User object to get the pw hashed, etc.
        '''
        assert isinstance(name, str)
        assert isinstance(pw, str)
        assert isinstance(attribs, dict)
        assert isinstance(perms, dict)
        assert name and pw and perms

        userobj = User({
            'name': name,
            'permissions': perms,
            'password': pw,
            'attributes': attribs
        })
        uid = self.mongo_service.create_new('users', {'name': userobj.name}, 'User', userobj.get_doc())
        pid = self.mongo_service.create_new('userpermissions', {'username': userobj.name}, 'UserPermissions', {
            "username": userobj.name,
            "applications": list(),
            "actions": dict(),
            "servers": list()
        })
        self.mongo_service.update_roottree(('global', 'users', userobj.name), 'users', uid)
        self.mongo_service.update_roottree(('global', 'users', userobj.name, 'permissions'), 'userpermissions', pid)

    def GetUserTokens(self, username):
        '''
        Get all auth tokens associated with user
        '''
        assert isinstance(username, str)
        assert username
        return [d['token'] for d in self.mongo_service.get('tokens', {'username': username}, multi=True)]

    def GetUserFromToken(self, token):
        '''
        Get username associated with token
        '''
        assert isinstance(token, str)
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
        assert isinstance(username, str)
        assert username

        token = Token({
            'username': username
        })
        tid = self.mongo_service.create_new('tokens', {'username': username, 'token': token.token}, 'Token',
                                            token.get_doc())
        self.mongo_service.update_roottree(('global', 'tokens', token.token), 'tokens', tid)
        return token

    def GetUsers(self):
        '''
        Get all valid users
        '''
        return [user for user in self.root['global']['users'] if user[0] != '_']

    def GetUser(self, username):
        '''
        Legacy API to get user OBJECT (not document)
        '''
        assert isinstance(username, str)
        assert username
        doc = self.mongo_service.get('users', {'username': username})
        return User(doc)

    def DeleteUser(self, name):
        '''
        Delete a single user and root_tree reference
        '''
        assert name
        assert isinstance(name, str)
        self.mongo_service.rm_roottree(('global', 'users', name))
        self.mongo_service.delete('users', {'username': name})

    def DeleteToken(self, token):
        '''
        Delete a token and root_tree reference
        '''
        assert token
        assert isinstance(token, str)
        self.mongo_service.rm_roottree(('global', 'tokens', token))
        self.mongo_service.delete('tokens', {'token': token})


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
        assert isinstance(app_name, str)
        doc = self.mongo_service.get('applications', {'app_name': app_name})
        return {k: doc[k] for k in doc if k[0] != '_'}

    def NewApplication(self, app_name):
        '''
        Create new application and all subcontainers and root_tree sub-references
        '''
        assert app_name
        assert isinstance(app_name, str)
        aid = self.mongo_service.create_new('applications', {'app_name': app_name}, 'Application', {})
        root_doc = {
            "builds": {"_doc": bson.DBRef('containers', self.NewContainer("BuildContainer", "builds", app_name))},
            "actions": {"_doc": bson.DBRef('containers', self.NewContainer("ActionContainer", "action", app_name))},
            "gitrepos": {"_doc": bson.DBRef('containers', self.NewContainer("GitRepoContainer", "gitrepos", app_name))},
            "gitdeploys": {"_doc": bson.DBRef('containers', self.NewContainer("GitDeployContainer", "gitdeploys", app_name))},
            "deployments": {"_doc": bson.DBRef('containers', self.NewContainer("DeploymentContainer", "deployments", app_name))},
            "groups": {"_doc": bson.DBRef('containers', self.NewContainer("GroupContainer", "groups", app_name))}
        }
        return self.mongo_service.update_roottree(('app', app_name), 'applications', aid, doc=root_doc)

    def DeleteApplication(self, app_name):
        '''
        Delete application and all root_tree references and sub-objects.
        '''
        assert app_name
        assert isinstance(app_name, str)
        self.mongo_service.rm_roottree(('app', app_name))
        self.mongo_service.delete('applications', {'app_name': app_name})
        self.mongo_service.delete('builds', {'app_name': app_name})
        self.mongo_service.delete('gitrepos', {'application': app_name})
        self.mongo_service.delete('gitdeploys', {'application': app_name})
        self.mongo_service.delete('deployments', {'application': app_name})
        self.mongo_service.delete('groups', {'application': app_name})

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
        assert isinstance(app_name, str)
        groups = [d['name'] for d in self.mongo_service.get('groups', {'application': app_name}, multi=True)]
        envs = list({d['environment'] for d in self.mongo_service.get('servers', {}, multi=True)})
        #envs = self.deps['ServerDataService'].GetEnvironments()
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

class GroupDataService(GenericChildDataService):
    def GetGroups(self, app):
        '''
        Get all groups for application.
        '''
        assert app
        assert isinstance(app, str)
        assert app in self.root['app']
        return [group for group in self.root['app'][app]['groups'] if group[0] != '_']

    def GetGroup(self, app, name):
        '''
        Get document for application group
        '''
        assert app and name
        assert isinstance(app, str)
        assert isinstance(name, str)
        return self.mongo_service.get('groups', {'application': app, 'name': name})

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
        assert isinstance(app, str)
        assert isinstance(name, str)
        assert elita.util.type_check.is_seq(gitdeploys)
        assert isinstance(description, str)
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

    def DeleteGroup(self, app, name):
        '''
        Delete a group object and root_tree reference
        '''
        assert app and name
        assert isinstance(app, str)
        assert isinstance(name, str)
        self.mongo_service.rm_roottree(('app', app, 'groups', name))
        self.mongo_service.delete('groups', {'application': app, 'name': name})

    def GetGroupServers(self, app, name, environments=None):
        '''
        Build sets from initialized servers in each gitdeploy in the group, then take intersection of all the sets
        If environments specified, take intersection with that set as well
        '''
        assert app and name
        assert isinstance(app, str)
        assert isinstance(name, str)
        group = self.GetGroup(app, name)
        assert group
        server_sets = [set(self.deps['GitDataService'].GetGitDeploy(app, gd)['servers']) for gd in group['gitdeploys']]
        if environments:
            envs = self.deps['ServerDataService'].GetEnvironments()
            for e in environments:
                assert e in envs
                server_sets.append(set(envs[e]))
        return list(set.intersection(*server_sets))

class JobDataService(GenericChildDataService):
    def GetAllActions(self, app_name):
        '''
        Get all actions associated with application. Get it from root_tree because the actions are dynamically populated
        at the start of each request.
        '''
        assert app_name
        assert isinstance(app_name, str)
        if 'actions' in self.root['app'][app_name]:
            return [action for action in self.root['app'][app_name]['actions'] if action[0] != '_']

    def GetAction(self, app_name, action_name):
        '''
        Get details (name, description, parameters) about all actions associated with application
        '''
        assert app_name and action_name
        assert isinstance(app_name, str)
        assert isinstance(action_name, str)
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
        self.mongo_service.create_new('job_data', None, None, {
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
        assert isinstance(job_id, str)
        return sorted([{'created_datetime': d['_id'].generation_time.isoformat(' '), 'data': d['data']} for
                       d in self.mongo_service.get('job_data', {'job_id': job_id}, multi=True)],
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
        diff = (now - doc['_id'].generation_time).total_seconds()
        self.mongo_service.modify('jobs', {'job_id': self.job_id}, ('status',), "completed")
        self.mongo_service.modify('jobs', {'job_id': self.job_id}, ('completed_datetime',), now)
        self.mongo_service.modify('jobs', {'job_id': self.job_id}, ('duration_in_seconds',), diff)
        self.NewJobData({"completed_results": results})

    def NewAction(self, app_name, action_name, params):
        '''
        Register new dynamically-loaded action in root_tree. These are loaded from plugins at the start of each request
        Note that action is added to in-memory root_tree object (not the root_tree record in mongo) because it is not
        persistent. Note further that this is *our* (meaning this thread's) root_tree and will only be in effect for the
        duration of this request, so we don't care about any root_tree updates by other threads running concurrently
        '''
        assert app_name and action_name and params
        assert isinstance(app_name, str)
        assert isinstance(action_name, str)
        assert elita.util.type_check.is_dictlike(params)
        logging.debug("NewAction: app_name: {}".format(app_name))
        logging.debug("NewAction: action_name: {}".format(action_name))
        if app_name in self.deps['ApplicationDataService'].GetApplications():
            self.root['app'][app_name]['actions'][action_name] = Action(app_name, action_name, params, self)
        else:
            logging.debug("NewAction: application '{}' not found".format(app_name))

    def ExecuteAction(self, app_name, action_name, params):
        '''
        Spawn async job for an action
        '''
        assert app_name and action_name and params
        assert isinstance(app_name, str)
        assert isinstance(action_name, str)
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
        return {
            'NewServer': {
                'name': name,
                'environment': environment,
                'attributes': attribs,
                'status': 'ok'
            }
        }

    def ChangeServer(self, name, doc):
        '''
        Change existing server object with data in doc
        '''
        assert name and doc
        assert isinstance(name, str)
        assert elita.util.type_check.is_dictlike(doc)
        assert name in self.root['server']
        prototype = Server({})  # get all valid default top-level properties
        assert all([key in prototype.get_doc() for key in doc])
        for p in elita.util.paths_from_nested_dict(doc):
            self.mongo_service.modify('servers', {'name': name}, p[:-1], p[-1])

    def DeleteServer(self, name):
        '''
        Delete a server object
        '''
        assert name
        assert isinstance(name, str)
        assert name in self.root['server']
        self.mongo_service.rm_roottree(('server', name))
        self.mongo_service.delete('servers', {'name': name})

    def GetGitDeploys(self, name):
        '''
        Get all gitdeploys initialized on a server. The canonical data source is the gitdeploy object (which contains
        a list of servers it's been initialized on)
        '''
        assert name
        assert isinstance(name, str)
        assert name in self.root['server']
        gitdeploys = self.mongo_service.get('gitdeploys', {'servers': {'$in': [name]}})
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
        gitrepo_doc = self.db['gitrepos'].find_one({'name': location['gitrepo']})
        logging.debug("NewGitDeploy: gitrepo_doc: {}".format(gitrepo_doc))
        if gitrepo_doc is None:
            return {'error': "invalid gitrepo (not found)"}
        location['gitrepo'] = bson.DBRef("gitrepos", gitrepo_doc['_id'])
        new_gd = {
            'name': name,
            'application': app_name,
            'servers': list(),
            'deployed_build': None,
            'options': {
                'favor': 'ours',
                'ignore-whitespace': 'true',
                'gitignore': []
            },
            'actions': {
                'prepull': [],
                'postpull': []
            },
            'location': location,
            'attributes': attributes,
        }
        #override defaults if specified
        if package:
            new_gd['package'] = package
        if options:
            for k in options:
                if k in new_gd['options']:
                    new_gd['options'][k] = options[k]
        if actions:
            util.change_dict_keys(actions, '.', EMBEDDED_YAML_DOT_REPLACEMENT)
            for k in actions:
                if k in new_gd['actions']:
                    new_gd['actions'][k] = actions[k]
        gd = GitDeploy(new_gd)
        gdo = self.db['gitdeploys'].find_and_modify(query={
            'name': gd.name,
            'application': gd.application
        }, update={
            '_class': "GitDeploy",
            'name': gd.name,
            'application': gd.application,
            'servers': gd.servers,
            'package': gd.package,
            'attributes': gd.attributes,
            'deployed_build': gd.deployed_build,
            'options': gd.options,
            'actions': gd.actions,
            'location': gd.location
        }, upsert=True, new=True)
        gdid = gdo['_id']
        self.parent.refresh_root()
        self.root['app'][app_name]['gitdeploys'][name] = {'_doc': bson.DBRef('gitdeploys', gdid)}
        return {"ok": "done"}

    def GetGitDeploys(self, app):
        return [k for k in self.root['app'][app]['gitdeploys'].keys() if k[0] != '_']


    def GetGitDeploy(self, app, name):
        doc = self.db['gitdeploys'].find_one({'name': name, 'application': app})
        #dereference embedded dbrefs
        doc['location']['gitrepo'] = self.db.dereference(doc['location']['gitrepo'])
        assert doc['location']['gitrepo'] is not None
        doc['location']['gitrepo']['keypair'] = self.db.dereference(doc['location']['gitrepo']['keypair'])
        assert doc['location']['gitrepo']['keypair'] is not None
        doc['location']['gitrepo']['gitprovider'] = self.db.dereference(doc['location']['gitrepo']['gitprovider'])
        assert doc['location']['gitrepo']['gitprovider'] is not None
        return {k: doc[k] for k in doc if k[0] != '_'}

    def GetGitDeployLocalPath(self, app, name):
        gd_doc = self.GetGitDeploy(app, name)
        gdm = GitDeployManager(gd_doc, self.parent)
        return gdm.get_path()

    def UpdateGitDeploy(self, app, name, doc):
        if 'location' in doc:
            assert 'gitrepo' in doc['location']
            grd = self.db['gitrepos'].find_one({'name': doc['location']['gitrepo'], 'application': app})
            assert grd
            doc['location']['gitrepo'] = bson.DBRef('gitrepos', grd['_id'])
        if 'actions' in doc:
            util.change_dict_keys(doc['actions'], '.', EMBEDDED_YAML_DOT_REPLACEMENT)
        self.parent.UpdateAppObject(name, doc, 'gitdeploys', "GitDeploy", app)

    def DeleteGitDeploy(self, app, name):
        self.parent.DeleteObject(self.root['app'][app]['gitdeploys'], name, 'gitdeploys')

    def GetGitProviders(self, objs=False):
        if objs:
            return [GitProvider(gp.doc) for gp in self.root['global']['gitproviders']]
        return [k for k in self.root['global']['gitproviders'].keys() if k[0] != '_']

    def GetGitProvider(self, name):
        doc = self.db['gitproviders'].find_one({'name': name})
        if not doc:
            return None
        return {k: doc[k] for k in doc if k[0] != '_'}

    def NewGitProvider(self, name, type, auth):
        if name in self.root['global']['gitproviders']:
            self.db['gitproviders'].remove({'name': name})
        gpobj = GitProvider({
            'name': name,
            'type': type,
            'auth': auth
        })
        gpo = self.db['gitproviders'].find_and_modify(query={
            'name': gpobj.name
        }, update={
            '_class': "GitProvider",
            'name': gpobj.name,
            'type': gpobj.type,
            'auth': gpobj.auth
        }, upsert=True, new=True)
        gpid = gpo['_id']
        self.parent.refresh_root()
        self.root['global']['gitproviders'][gpobj.name] = {'_doc': bson.DBRef('gitproviders', gpid)}

    def UpdateGitProvider(self, name, doc):
        self.parent.UpdateObject(name, doc, 'gitproviders', "GitProvider")

    def DeleteGitProvider(self, name):
        self.parent.DeleteObject(self.root['global']['gitproviders'], name, 'gitproviders')

    def GetGitRepos(self, app):
        return [k for k in self.root['app'][app]['gitrepos'].keys() if k[0] != '_']

    def GetGitRepo(self, app, name):
        doc = self.db['gitrepos'].find_one({'name': name, 'application': app})
        return {k: doc[k] for k in doc if k[0] != '_'}

    def NewGitRepo(self, app, name, keypair, gitprovider, uri=None, existing=False):
        gp_doc = self.db['gitproviders'].find_one({'name': gitprovider})
        if gp_doc is None:
            return {'NewGitRepo': "gitprovider '{}' is unknown".format(gitprovider)}
        kp_doc = self.db['keypairs'].find_one({'name': keypair})
        if kp_doc is None:
            return {'NewGitRepo': "keypair '{}' is unknown".format(keypair)}
        gr_obj = GitRepo({
            'name': name,
            'application': app,
            'keypair': bson.DBRef("keypairs", kp_doc['_id']),
            'gitprovider': bson.DBRef("gitproviders", gp_doc['_id']),
            'uri': uri,
            'last_build': None
        })
        gro = self.db['gitrepos'].find_and_modify(query={
            'name': gr_obj.name,
            'application': gr_obj.application
        }, update={
            '_class': "GitRepo",
            'name': gr_obj.name,
            'application': gr_obj.application,
            'keypair': gr_obj.keypair,
            'gitprovider': gr_obj.gitprovider,
            'uri': gr_obj.uri,
            'last_build': gr_obj.last_build
        }, upsert=True, new=True)
        gr_id = gro['_id']
        self.parent.refresh_root()
        self.root['app'][app]['gitrepos'][name] = {
            '_doc': bson.DBRef('gitrepos', gr_id)
        }
        return {'NewGitRepo': 'ok'}

    def UpdateGitRepo(self, app, name, doc):
        gro = GitRepo(self.GetGitRepo(app, name))
        gro.update_values(doc)
        grd = gro.get_doc()
        existing = [doc['_id'] for doc in self.db['gitrepos'].find({'name': name, 'application': app})]
        if len(existing) > 0:
            if len(existing) > 1:
                # we should never have more than one, if so keep the 'top' one
                logging.debug("WARNING: multiple gitrepo documents found, dropping all but the first")
                for id in existing[1:]:
                    self.db['gitrepos'].remove({'_id': id})
            grd['_id'] = existing[0]
        else:
            logging.debug("UpdateGitRepo: WARNING: existing doc not found!")
            return
        grd['_class'] = "GitRepo"
        self.db['gitrepos'].save(grd)

    def DeleteGitRepo(self, app, name):
        self.parent.DeleteObject(self.root['app'][app]['gitrepos'], name, 'gitrepos')

class DeploymentDataService(GenericChildDataService):
    def NewDeployment(self, app, build_name, environments, groups, servers, gitdeploys):
        dpo = Deployment({
            'name': "",
            'application': app,
            'build_name': build_name,
            'environments': environments,
            'groups': groups,
            'servers': servers,
            'gitdeploys': gitdeploys,
            'status': 'created',
            'job_id': ''
        })
        did = self.db['deployments'].insert({
            '_class': 'Deployment',
            'name': dpo.name,
            'application': dpo.application,
            'build_name': dpo.build_name,
            'environments': dpo.environments,
            'groups': dpo.groups,
            'servers': dpo.servers,
            'gitdeploys': dpo.gitdeploys,
            'status': dpo.status,
            'job_id': dpo.job_id
        })
        # we don't know the deployment 'name' until it's inserted
        doc = self.db['deployments'].find_one({'_id': did})
        doc['name'] = str(did)
        self.db['deployments'].save(doc)
        self.parent.refresh_root()
        self.root['app'][app]['deployments'][str(did)] = {
            '_doc': bson.DBRef('deployments', did)
        }
        return {
            'NewDeployment': {
                'application': app,
                'id': str(did)
        }}

    def GetDeployments(self, app):
        return [k for k in self.root['app'][app]['deployments'].keys() if k[0] != '_']

    def UpdateDeployment(self, app, name, doc):
        self.parent.UpdateAppObject(name, doc, 'deployments', "Deployment", app)

class KeyDataService(GenericChildDataService):
    def GetKeyPairs(self):
        return [k for k in self.root['global']['keypairs'].keys() if k[0] != '_']

    def GetKeyPair(self, name):
        doc = self.db['keypairs'].find_one({'name': name})
        if not doc:
            return None
        kobj = KeyPair(doc)
        return kobj.get_doc()

    def NewKeyPair(self, name, attribs, key_type, private_key, public_key):
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
        kpo = self.db['keypairs'].find_and_modify(query={
            'name': kp_obj.name
        }, update={
            '_class': "KeyPair",
            'name': kp_obj.name,
            'attributes': kp_obj.attributes,
            'key_type': kp_obj.key_type,
            'private_key': kp_obj.private_key,
            'public_key': kp_obj.public_key
        }, upsert=True, new=True)
        kp_id = kpo['_id']
        self.root['global']['keypairs'][kp_obj.name] = {
            '_doc': bson.DBRef("keypairs", kp_id)
        }
        return {
            'NewKeyPair': {
                'status': 'ok'
            }
        }

    def UpdateKeyPair(self, name, doc):
        self.parent.UpdateObject(name, doc, "keypairs", "KeyPair")

    def DeleteKeyPair(self, name):
        self.parent.DeleteObject(self.root['global']['keypairs'], name, "keypairs")


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

        self.buildsvc = BuildDataService(self.mongo_service, root)
        self.usersvc = UserDataService(self.mongo_service, root)
        self.appsvc = ApplicationDataService(self.mongo_service, root)
        self.jobsvc = JobDataService(self.mongo_service, root)
        self.serversvc = ServerDataService(self.mongo_service, root)
        self.gitsvc = GitDataService(self.mongo_service, root)
        self.keysvc = KeyDataService(self.mongo_service, root)
        self.deploysvc = DeploymentDataService(self.mongo_service, root)
        self.actionsvc = ActionService(self)
        self.groupsvc = GroupDataService(self.mongo_service, root)

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

        #passed in if this is part of an async job
        self.job_id = job_id
        #super ugly below - only exists for plugin access
        if job_id is not None:
            self.salt_controller = salt_control.SaltController(self.settings)
            self.remote_controller = salt_control.RemoteCommands(self.salt_controller)
            self.deploy_controller = deploy.DeployController(self)

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
        'server': bson.DBRef("", None),
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
    default_values = {
        'name': None,  # "name" for consistency w/ other models, even though it's really id
        'application': None,
        'build_name': None,
        'environments': None,
        'groups': None,
        'servers': None,
        'gitdeploys': None,
        'status': None,
        'progress': dict(),
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

class User(GenericDataModel):
    default_values = {
        'username': None,
        'password': None,
        'hashed_pw': None,
        'salt': None,
        'attributes': dict()
    }

    def init_hook(self):
        assert self.hashed_pw is not None or self.password is not None
        self.salt = base64.urlsafe_b64encode(uuid.uuid4().bytes) if self.salt is None else self.salt
        self.hashed_pw = self.hash_pw(self.password) if self.hashed_pw is None else self.hashed_pw
        self.password = None

    def hash_pw(self, pw):
        assert pw is not None
        return base64.urlsafe_b64encode(hashlib.sha512(pw + self.salt).hexdigest())

    def validate_password(self, pw):
        return self.hashed_pw == self.hash_pw(pw)

    def change_password(self, new_pw):
        self.hashed_pw = self.hash_pw(new_pw)

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
        return self.doc is not None and self.doc['_class'] == 'ActionContainer'

    def __getitem__(self, key):
        key = self.__keytransform__(key)
        if self.is_action():
            return self.tree[key]
        if key in self.tree:
            if key == '_doc':
                return self.tree[key]
            doc = self.db.dereference(self.tree[key]['_doc'])
            if doc is None:
                raise KeyError
            return RootTree(self.db, self.updater, self.tree[key], doc)
        else:
            raise KeyError

    def __setitem__(self, key, value):
        self.tree[key] = value
        if not self.is_action():     # dynamically populated each request
            self.updater.update()

    def __delitem__(self, key):
        del self.tree[key]
        self.updater.update()
        return

    def __iter__(self):
        return iter(self.tree)

    def __len__(self):
        return len(self.tree)

    def __keytransform__(self, key):
        return key

class RootTreeUpdater:
    __metaclass__ = util.LoggingMetaClass

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
    '''Independent class to migrate/validate the root tree and potentially all docs
        Intended to run prior to main application, to migrate schema or fix problems
    '''
    __metaclass__ = util.LoggingMetaClass

    def __init__(self, root, db):
        self.root = root
        self.db = db

    def run(self):
        logging.debug("running")
        self.check_root()
        self.check_doc_consistency()
        self.check_toplevel()
        self.check_containers()
        self.check_global()
        self.check_users()
        self.check_user_permissions()
        self.check_apps()
        self.check_jobs()
        self.check_deployments()
        self.check_servers()
        self.check_gitdeploys()
        self.check_gitrepos()
        self.check_groups()
        self.SaveRoot()

    def SaveRoot(self):
        if '_id' in self.root:
            self.db['root_tree'].update({"_id": self.root['_id']}, self.root)
        else:
            self.db['root_tree'].insert(self.root)

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
            'servers'
        ]
        for c in collects:
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
                if c == 'builds':
                    if d['build_name'] not in self.root['app'][d['app_name']]['builds']:
                        logging.warning("orphan build object: '{}/{}', adding to root tree".format(d['app_name'], d['build_name']))
                        self.root['app'][d['app_name']]['builds'][d['build_name']] = {'_doc': bson.DBRef('builds', d['_id'])}
                if c == 'gitproviders':
                    if d['name'] not in self.root['global']['gitproviders']:
                        logging.warning("orphan gitprovider object: '{}', adding to root tree".format(d['name']))
                        self.root['global']['gitproviders'][d['name']] = {'_doc': bson.DBRef('gitproviders', d['_id'])}
                if c == 'gitrepos':
                    if d['name'] not in self.root['app'][d['application']]['gitrepos']:
                        logging.warning("orphan gitrepo object: '{}/{}', adding to root tree".format(d['application'], d['name']))
                        self.root['app'][d['application']]['gitrepo'][d['name']] = {'_doc': bson.DBRef('gitrepos', d['_id'])}
                if c == 'gitdeploys':
                    if d['name'] not in self.root['app'][d['application']]['gitdeploys']:
                        logging.warning("orphan gitdeploy object: '{}/{}', adding to root tree".format(d['application'], d['name']))
                        self.root['app'][d['application']]['gitdeploys'][d['name']] = {'_doc': bson.DBRef('gitdeploys', d['_id'])}
                if c == 'jobs':
                    if d['job_id'] not in self.root['job']:
                        logging.warning("orphan job object: '{}', adding to root tree".format(d['job_id']))
                        self.root['job'][d['job_id']] = {'_doc': bson.DBRef('jobs', d['_id'])}
                if c == 'tokens':
                    if d['token'] not in self.root['global']['tokens']:
                        logging.warning("orphan token object: '{}', adding to root tree".format(d['token']))
                        self.root['global']['tokens'][d['token']] = {'_doc': bson.DBRef('tokens', d['_id'])}
                if c == 'users':
                    if d['name'] not in self.root['global']['users']:
                        logging.warning("orphan user object: '{}', adding to root tree".format(d['name']))
                        self.root['global']['users'][d['name']] = {'_doc': bson.DBRef('users', d['_id'])}
                if c == 'servers':
                    if d['name'] not in self.root['server']:
                        logging.warning("orphan server object: '{}', adding to root tree".format(d['name']))
                        self.root['server'][d['name']] = {'_doc': bson.DBRef('servers', d['_id'])}


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
        if 'admin' not in self.root['global']['users']:
            logging.warning("admin user not found")
            uobj = User({
                'name': 'admin',
                'password': 'elita',
                'permissions': {
                    'apps': {
                        '*': 'read/write',
                        '_global': 'read/write'
                    },
                    'actions': {
                        '*': {
                            '*': 'execute'
                        }
                    },
                    'servers': '*'
                }
            })
            id = self.db['users'].insert({
            "_class": "User",
            "name": uobj.name,
            "hashed_pw": uobj.hashed_pw,
            "attributes": uobj.attributes,
            "salt": uobj.salt,
            "permissions": uobj.permissions
            })
            self.root['global']['users']['admin'] = {
                '_doc': bson.DBRef('users', id)
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

    def check_user_permissions(self):
        for u in self.db['users'].find():
            if 'permissions' not in u:
                logging.warning("permissions object not found for user {}; fixing with empty obj"
                              .format(u['name']))
                u['permissions'] = {
                    'apps': {},
                    'actions': {},
                    'servers': []
                }
            for o in ('apps', 'actions', 'servers'):
                if o not in u['permissions']:
                    logging.warning("{} not found in permissions object for user {}; fixing with empty "
                                        "obj".format(o, u['name']))
                    u['permissions'][o] = list() if o == 'servers' else dict()
            if not isinstance(u['permissions']['servers'], list):
                logging.warning("servers key under permissions object for user {} is not a list; fixing"
                              .format(u['name']))
                u['permissions']['servers'] = list(u['permissions']['servers'])
            for o in ('apps', 'actions'):
                if not isinstance(u['permissions'][o], dict):
                    logging.warning("{} key under permissions object for user {} is not a dict; invalid "
                                        "so replacing with empty dict".format(o, u['name']))
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
            if 'environment' not in d:
                logging.warning("environment field not found for server {}; fixing".format(d['_id']))
                d['environment'] = ""
                update_list.append(d)
            if 'status' not in d:
                logging.warning("status field not found for server {}; fixing".format(d['_id']))
                d['status'] = "ok"
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
        self.root = dict() if self.root is None else self.root
        if '_class' in self.root:
            logging.warning("'_class' found in base of root; deleting")
            del self.root['_class']
        if '_doc' not in self.root:
            logging.warning("'_doc' not found in base of root")
            self.root['_doc'] = self.NewContainer('Root', 'Root', '')
        rt_list = [d for d in self.db['root_tree'].find({'_lock': {'$exists': False}})]
        if not rt_list:
            logging.warning("no root_tree found!")
        if len(rt_list) > 1:
            logging.warning("duplicate root_tree docs found! Removing all but the first")
            for d in rt_list[1:]:
                self.db['root_tree'].remove({'_id': d['_id']})


