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
import random
import time

import elita
from elita.crypto import keypair
from elita.deployment import deploy, salt_control
import util
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
        self.LOCK_MAX_TRIES = timeout

    def create_new(self, collection, name, classname, doc):
        '''
        Creates new document in collection. Remove any existing.
        '''

        existing = [d for d in self.db[collection].find({'name': name})]
        doc['_class'] = classname
        id = self.db[collection].save(doc)
        if existing:
            self.db[collection].remove({'name': name, '$not': {'_id': id}})
        return True

    def modify(self, collection, name, doc):
        '''
        Modifies document with the keys in doc. Does so atomically but remember that any key will overwrite the existing
        key.
        '''
        pass

    def delete(self, collection, name):
        '''
        Drop a document from the collection
        '''
        pass

    def update_roottree(self, path, collection, id):
        '''
        Update the root tree at path [must be a tuple of indices: ('app', 'myapp', 'builds', '123-foo')] with DBRef
        '''
        assert hasattr(path, '__iter__')
        assert isinstance(collection, str)
        assert id.__class__.__name__ == 'ObjectId'
        path_dot_notation = '.'.join(path)
        root_tree_doc = {
            '_doc': bson.DBRef(collection, id)
        }
        result = self.db['root_tree'].update({}, {'$set': {path_dot_notation: root_tree_doc}})
        return result['n'] == 1 and result['updatedExisting'] and not result['err']

class GenericChildDataService:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, parent):
        self.parent = parent
        self.db = parent.db
        self.root = parent.root
        self.settings = parent.settings

class BuildDataService(GenericChildDataService):
    def GetBuilds(self, app_name):
        return [k for k in self.root['app'][app_name]['builds'].keys() if k[0] != '_']

    def NewBuild(self, app_name, build_name, attribs):
        buildobj = Build({
            'app_name': app_name,
            'build_name': build_name,
            'attributes': attribs
        })
        new_doc = {
            '_class': "Build",
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
        bobj = self.GetBuild(app, build)
        packages = dict(bobj.packages.items() + packages.items())
        #generate files from packages (avoid dupes)
        files = [{"file_type": packages[p]['file_type'], "path": packages[p]['filename']} for p in packages]
        self.UpdateBuild(app, {
            "build_name": bobj.build_name,
            "packages": packages,
            "files": files
        })

    def UpdateBuild(self, app, doc):
        logging.debug("UpdateBuild: app: {}; doc: {}".format(app, doc))
        self.parent.UpdateGenericObject(doc['build_name'], doc, "builds", "Build", {'build_name': doc['build_name'],
                                                                                    'app_name': app})
    def DeleteBuildStorage(self, app_name, build_name):
        dir = self.settings['elita.builds.dir']
        path = "{root_dir}/{app}/{build}".format(root_dir=dir, app=app_name, build=build_name)
        logging.debug("DeleteBuildStorage: path: {}".format(path))
        if os.path.isdir(path):
            logging.debug("DeleteBuildStorage: remove_build: deleting")
            shutil.rmtree(path)

    def DeleteBuild(self, app_name, build_name):
        self.DeleteBuildStorage(app_name, build_name)
        self.parent.DeleteObject(self.root['app'][app_name]['builds'], build_name, "builds")

    def refresh_root(self):
        # when running long async actions the root tree passed to constructor may be stale by the time we try to update
        # so just prior to altering it, we refresh from the DB
        req = Request()
        req.db = self.db
        self.root = elita.RootService(req)
    def GetBuild(self, app_name, build_name):
        return Build(self.root['app'][app_name]['builds'][build_name].doc)

    def GetBuildDoc(self, app_name, build_name):
        bobj = self.GetBuild(app_name, build_name)
        return bobj.get_doc()

class UserDataService(GenericChildDataService):
    def NewUser(self, name, pw, perms, attribs):
        userobj = User({
                                         'name': name,
            'permissions': perms,
            'password': pw,
            'attributes': attribs
        })
        id = self.db['users'].insert({
            "_class": "User",
            "name": userobj.name,
            "hashed_pw": userobj.hashed_pw,
            "attributes": userobj.attributes,
            "salt": userobj.salt,
            "permissions": userobj.permissions
        })
        pid = self.db['userpermissions'].insert({
            "_class": "UserPermissions",
            "username": userobj.name,
            "applications": list(),
            "actions": dict(),
            "servers": list()
        })
        self.parent.refresh_root()
        self.root['global']['users'][userobj.name] = {
            "_doc": bson.DBRef("users", id)
        }
        self.parent.refresh_root()
        self.root['global']['users'][userobj.name]['permissions'] = {
            '_doc': bson.DBRef("userpermissions", pid)
        }

    def SaveUser(self, userobj):
        #find and update user document
        doc = self.db['users'].find_one({"name": userobj.name})
        assert doc is not None
        doc['hashed_pw'] = userobj.hashed_pw
        doc['attributes'] = userobj.attributes
        doc['salt'] = userobj.salt
        doc['permissions'] = userobj.permissions
        self.db['users'].update({"_id": doc["_id"]}, doc)

    def GetUserTokens(self, username):
        return [d['token'] for d in self.db['tokens'].find({"username": username})]

    def GetUserFromToken(self, token):
        pp = pprint.PrettyPrinter(indent=4)
        logging.debug("GetUserFromToken: token: {}".format(token))
        tok = self.root['global']['tokens'][token]
        doc = tok.doc
        logging.debug("GetUserFromToken: doc: {}".format(pp.pformat(doc)))
        return doc['username']

    def GetAllTokens(self):
        return [k for k in self.root['global']['tokens'].keys() if k[0] != '_']

    def NewToken(self, username):
        token = Token({
            'username': username
        })
        id = self.db['tokens'].insert({
            'username': username,
            'token': token.token,
            '_class': "Token"
        })
        self.parent.refresh_root()
        self.root['global']['tokens'][token.token] = {
            "_doc": bson.DBRef("tokens", id)
        }
        return token

    def GetUsers(self):
        return [k for k in self.root['global']['users'].keys() if k[0] != '_']

    def GetUser(self, username):
        return User(self.root['global']['users'][username].doc)

    def DeleteUser(self, name):
        self.parent.DeleteObject(self.root['global']['users'], name, "users")

    def DeleteToken(self, token):
        self.parent.DeleteObject(self.root['global']['tokens'], token, "tokens")


class ApplicationDataService(GenericChildDataService):
    def GetApplications(self):
        return [k for k in self.root['app'].keys() if k[0] != '_']

    def GetApplication(self, app_name):
        docs = [d for d in self.db['application'].find({'app_name': app_name})]
        assert len(docs) > 0
        if len(docs) > 1:
            elita.logging.debug("GetApplication: WARNING: more than one application named {}".format(app_name))
        return {k: docs[0][k] for k in docs[0] if k[0] != '_'}

    def NewApplication(self, app_name):
        id = self.db['applications'].insert({'_class': "Application", "app_name": app_name})
        self.parent.refresh_root()
        self.root['app'][app_name] = {
            "_doc": bson.DBRef("applications", id),
            "builds": {"_doc": self.parent.NewContainer("BuildContainer", "builds", app_name)},
            "actions": {"_doc": self.parent.NewContainer("ActionContainer", "action", app_name)},
            "gitrepos": {"_doc": self.parent.NewContainer("GitRepoContainer", "gitrepos", app_name)},
            "gitdeploys": {"_doc": self.parent.NewContainer("GitDeployContainer", "gitdeploys", app_name),},
            "deployments": {"_doc": self.parent.NewContainer("DeploymentContainer", "deployments", app_name)},
            "groups": {"_doc": self.parent.NewContainer("GroupContainer", "groups", app_name)}
        }

    def ChangeApplication(self, app_name, data):
        self.parent.ModifyObject("applications", app_name, data, name_key="app_name")

    def DeleteApplication(self, app_name):
        self.parent.DeleteObject(self.root['app'], app_name, 'applications')

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
        groups = self.parent.groupsvc.GetGroups(app_name)
        envs = self.parent.serversvc.GetEnvironments()
        census = dict()
        for e in envs:
            census[e] = dict()
            for g in groups:
                g_servers = self.parent.groupsvc.GetGroupServers(app_name, g, environments=[e])
                census[e][g] = dict()
                for s in g_servers:
                    census[e][g][s] = dict()
                    group_doc = self.parent.groupsvc.GetGroup(app_name, g)
                    for gd in group_doc['gitdeploys']:
                        gd_doc = self.parent.gitsvc.GetGitDeploy(app_name, gd)
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
        return [k for k in self.root['app'][app]['groups'] if k[0] != '_']

    def GetGroup(self, app, name):
        docs = [d for d in self.db['groups'].find({'application': app, 'name': name})]
        assert len(docs) > 0
        if len(docs) > 1:
            elita.logging.debug("GetGroup: WARNING: more than one group {} in application {}".format(name, app))
        doc = docs[0]
        return {k: doc[k] for k in doc if k[0] != '_'}

    def NewGroup(self, app, name, gitdeploys, rolling_deploy=False, description="", attributes={}):
        gp = Group({
            "application": app,
            "name": name,
            "description": description,
            "gitdeploys": gitdeploys,
            "attributes": attributes,
            "rolling_deploy": rolling_deploy
        })

        gid = self.db['groups'].insert({
            '_class': 'Group',
            'application': gp.application,
            'name': gp.name,
            'description': gp.description,
            'attributes': gp.attributes,
            'gitdeploys': gp.gitdeploys,
            'rolling_deploy': gp.rolling_deploy
        })

        self.parent.refresh_root()
        self.root['app'][app]['groups'][gp.name] = {
            '_doc': bson.DBRef("groups", gid)
        }

    def DeleteGroup(self, app, name):
        self.parent.DeleteObject(self.root['app'][app]['groups'], name, 'groups')

    def GetGroupServers(self, app, name, environments=None):
        # build sets from initialized servers in each gitdeploy in the group
        # then take intersection of all the sets
        # if environments specified, take intersection with that set as well
        group = self.GetGroup(app, name)
        assert group is not None
        server_sets = [set(self.parent.gitsvc.GetGitDeploy(app, gd)['servers']) for gd in group['gitdeploys']]
        if environments:
            envs = self.parent.serversvc.GetEnvironments()
            for e in environments:
                assert e in envs
                server_sets.append(set(envs[e]))
        return list(set.intersection(*server_sets))

class JobDataService(GenericChildDataService):
    def GetAllActions(self, app_name):
        if 'actions' in self.root['app'][app_name]:
            return [action for action in self.root['app'][app_name]['actions'] if action[0] != '_']

    def GetAction(self, app_name, action_name):
        actions = self.parent.actionsvc.get_action_details(app_name, action_name)
        return {k: actions[k] for k in actions if k is not "callable"}

    def NewJob(self, name, job_type, data):
        job = Job({
            'status': "running",
            'name': name,
            'job_type': job_type,
            'data': data,
            'attributes': {
                'name': name
            }
        })
        jid = self.db['jobs'].insert({
            '_class': 'Job',
            'name': job.name,
            'job_id': str(job.job_id),
            'job_type': job.job_type,
            'data': job.data,
            'status': job.status,
            'attributes': job.attributes
        })
        self.parent.refresh_root()
        self.root['job'][str(job.job_id)] = {
            "_doc": bson.DBRef("jobs", jid)
        }
        return job

    def NewJobData(self, data):
        assert self.parent.job_id
        self.db['job_data'].insert({
            'job_id': self.parent.job_id,
            'data': data
        })

    def GetJobs(self, active):
        return [d['job_id'] for d in self.db['jobs'].find({'status': 'running'} if active else {})]

    def GetJobData(self, job_id):
        return sorted([{'created_datetime': d['_id'].generation_time.isoformat(' '), 'data': d['data']} for
                       d in self.db['job_data'].find({'job_id': job_id})], key=lambda k: k['created_datetime'])

    def SaveJobResults(self, results):
        assert self.parent.job_id
        now = datetime.datetime.now(tz=pytz.utc)
        doc = self.db['jobs'].find_one({'job_id': self.parent.job_id})
        diff = (now - doc['_id'].generation_time).total_seconds()
        res = self.db['jobs'].update({'job_id': self.parent.job_id}, {'$set': {'status': "completed",
                                                                   'completed_datetime': now,
                                                                   'duration_in_seconds': diff}})
        logging.debug("SaveJobResults: update job doc: {}".format(res))
        self.NewJobData({"completed_results": results})

    def NewAction(self, app_name, action_name, params):
        logging.debug("NewAction: app_name: {}".format(app_name))
        logging.debug("NewAction: action_name: {}".format(action_name))
        self.parent.refresh_root()
        self.root['app'][app_name]['actions'][action_name] = Action(app_name, action_name, params, self)
        if app_name in self.parent.appsvc.GetApplications():
            self.parent.refresh_root()
            self.root['app'][app_name]['actions'][action_name] = Action(app_name, action_name, params, self)
        else:
            logging.debug("NewAction: application '{}' not found".format(app_name))

    def ExecuteAction(self, app_name, action_name, params):
        return self.parent.actionsvc.async(app_name, action_name, params)

class ServerDataService(GenericChildDataService):
    def GetServers(self):
        return [k for k in self.root['server'].keys() if k[0] != '_' and k != 'environments']

    def NewServer(self, name, attribs, environment, existing=False):
        try:
            server = Server({
                'name': name,
                'status': 'new',
                'server_type': 'unknown',
                'environment': environment,
                'attributes': attribs
            })
        except elita_exceptions.SaltServerNotAccessible:
            return {
                'NewServer': {
                    'status': 'error',
                    'message': "server not accessible via salt"
                }
            }
        so = self.db['servers'].find_and_modify(query={
            'name': server.name,
        }, update={
            '_class': "Server",
            'name': server.name,
            'status': server.status,
            'server_type': server.server_type,
            'environment': server.environment,
            'gitdeploys': [],
            'attributes': server.attributes
        }, upsert=True, new=True)
        sid = so['_id']
        self.parent.refresh_root()
        self.root['server'][name] = {
            '_doc': bson.DBRef('servers', sid),
            'gitdeploys': {"_doc": self.parent.NewContainer("GitDeployContainer", "gitdeploys", name)}
        }
        return {
            'NewServer': {
                'status': 'ok'
            }
      }

    def ChangeServer(self, name, changed_keys):
        '''
        Modify data in existing server. changed_keys is a dict of top-level keys to replace. Each one will *replace*
        the entire top-level key!
        '''
        prototype = Server({})
        assert isinstance(changed_keys, dict)
        # do each key separately to keep atomic
        for k in changed_keys:
            if hasattr(prototype, k):
                self.db['servers'].find_and_modify(query={
                    'name': name
                }, update={
                    '$set': {k: changed_keys[k]}
                })

    def DeleteServer(self, name):
        self.parent.DeleteObject(self.root['server'], name, 'servers')

    def GetGitDeploys(self, name):
        servers = [s for s in self.db['servers'].find({'name': name})]
        assert servers
        s = servers[0]
        if len(servers) > 1:
            logging.debug("(Server->)GetGitDeploys: WARNING: {} server docs found for {}; removing all but the first".format(len(servers), name))
            for s in servers[1:]:
                self.db['servers'].remove({'_id': s['_id']})
        s['gitdeploys'] = [self.db.dereference(d) for d in s['gitdeploys']]
        return [{'application': gd['application'], 'gitdeploy_name': gd['name']} for gd in s['gitdeploys']]

    def GetEnvironments(self):
        environments = dict()
        srvs = self.GetServers()
        for s in srvs:
            server = [d for d in self.db['servers'].find({'name': s})]
            if len(server) > 1:
                logging.debug("(Server->)GetEnvironments: more than one doc found for server {}".format(s))
            doc = server[0]
            env = doc['environment']
            if env in environments:
                environments[env].update([s])
            else:
                environments[env] = {s}
        return {k: list(environments[k]) for k in environments}


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
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, settings, db, root, job_id=None):
        self.settings = settings
        self.db = db
        self.root = root
        self.ms = MongoService(db)
        # potential reference cycles
        self.buildsvc = BuildDataService(self)
        self.usersvc = UserDataService(self)
        self.appsvc = ApplicationDataService(self)
        self.jobsvc = JobDataService(self)
        self.serversvc = ServerDataService(self)
        self.gitsvc = GitDataService(self)
        self.keysvc = KeyDataService(self)
        self.deploysvc = DeploymentDataService(self)
        self.actionsvc = ActionService(self)
        self.groupsvc = GroupDataService(self)
        #passed in if this is part of an async job
        self.job_id = job_id
        #super ugly below - only exists for plugin access
        if job_id is not None:
            self.salt_controller = salt_control.SaltController(self.settings)
            self.remote_controller = salt_control.RemoteCommands(self.salt_controller)
            self.deploy_controller = deploy.DeployController(self)

    def refresh_root(self):
        # when running long async actions the root tree passed to constructor may be stale by the time we try to update
        # so just prior to altering it, we refresh from the DB
        req = Request()
        req.db = self.db
        self.root = elita.RootService(req)

    def ModifyObject(self, collection_name, name, modify_keys, name_key="name"):
        '''Replace only the keys in modify_keys in the referenced document'''
        docs = [d for d in self.db[collection_name].find({name_key: name})]
        assert len(docs) > 0
        if len(docs) > 1:
            elita.logging.debug("ModifyObject: found multiple docs in collection: {}; name: {}"
                                .format(collection_name, name))
            for d in docs[1:]:
                self.db[collection_name].remove({'_id': d['_id']})
        doc = docs[0]
        for k in modify_keys:
            doc[k] = modify_keys[k]
        self.db[collection_name].save(doc)

    def UpdateObject(self, name, doc, collection_name, class_name):
        self.UpdateGenericObject(name, doc, collection_name, class_name, {"name": name})

    def UpdateAppObject(self, name, doc, collection_name, class_name, app):
        self.UpdateGenericObject(name, doc, collection_name, class_name, {"name": name, "application": app})

    def UpdateGenericObject(self, name, doc, collection_name, class_name, query):
        old_doc = self.db[collection_name].find_one(query)
        if old_doc:
            cobj = globals()[class_name](old_doc)
            cobj.update_values(doc)
            new_doc = cobj.get_doc()
            new_doc['_id'] = old_doc['_id']
            new_doc['_class'] = class_name
            self.db[collection_name].save(new_doc)

    def NewContainer(self, class_name, name, parent):
        cdoc = self.db['containers'].insert({'_class': class_name,
                                         'name': name,
                                         'parent': parent})
        return bson.DBRef('containers', cdoc)

    def DeleteObject(self, container, key, collection):
        id = container[key].doc['_id']
        self.db[collection].remove({'_id': id})
        self.refresh_root()
        del container[key]

    def Dereference(self, dbref):
        return self.db.dereference(dbref)

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
        self.check_root_locks()
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
        if '_lock' not in rt_list[0]:
            logging.warning("_lock field not found in root_tree; fixing")
            rt_list[0]['_lock'] = False
            self.db['root_tree'].save(rt_list[0])

    def check_root_lock(self):
        stale_lock = [d for d in self.db['root_tree'].find({'_lock': True})]
        if stale_lock:
            logging.warning("found stale root_tree lock; resetting".format(len(stale_lock)))
            self.db['root_tree'].update({'_lock': True}, {'$set': {'_lock': False}})


