import collections
import hashlib
import uuid
import base64
import os.path
import shutil
import bson
import pprint
import datetime
import pytz

import util
from action import ActionService

# URL model:
# root/app/
# root/app/{app_name}/builds/
# root/app/{app_name}/builds/{build_name}
# root/app/{app_name}/environments/
# root/app/{app_name}/environments/{env_name}/deployments
# root/app/{app_name}/environments/{env_name}/deployments/{deployment_id}
# root/app/{app_name}/environments/{env_name}/servers
# root/app/{app_name}/environemnt/{env_name}/servers/{server_name}


class GenericChildDataService:
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
        id = self.db['builds'].insert({'_class': "Build",
                                       'build_name': buildobj.build_name,
                                       'files': buildobj.files,
                                       'stored': buildobj.stored,
                                       'app_name': buildobj.app_name,
                                       'packages': buildobj.packages,
                                       'attributes': buildobj.attributes})
        self.root['app'][app_name]['builds'][build_name] = {
            "_doc": bson.DBRef("builds", id)
        }

    def UpdateBuildProperties(self, app, properties):
        bobj = self.GetBuild(app, properties['build_name'])
        for p in properties:
            setattr(bobj, p, properties[p])
        self.UpdateBuild(bobj)

    def UpdateBuild(self, buildobj):
        doc = self.db['builds'].find_one({"build_name": buildobj.build_name})
        assert doc is not None
        doc["files"] = buildobj.files
        doc["stored"] = buildobj.stored
        doc["packages"] = buildobj.packages
        doc["master_file"] = buildobj.master_file
        doc["attributes"] = buildobj.attributes
        self.db['builds'].update({"_id": doc['_id']}, doc)

    def DeleteBuildStorage(self, app_name, build_name):
        dir = self.settings['daft.builds.dir']
        path = "{root_dir}/{app}/{build}".format(root_dir=dir, app=app_name, build=build_name)
        util.debugLog(self, "DeleteBuildStorage: path: {}".format(path))
        if os.path.isdir(path):
            util.debugLog(self, "DeleteBuildStorage: remove_build: deleting")
            shutil.rmtree(path)

    def DeleteBuild(self, app_name, build_name):
        self.DeleteBuildStorage(app_name, build_name)
        self.parent.DeleteObject(self.root['app'][app_name]['builds'], build_name, "builds")

    def GetBuild(self, app_name, build_name):
        return Build(self.root['app'][app_name]['builds'][build_name].doc)

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
        self.root['global']['users'][userobj.name] = {
            "_doc": bson.DBRef("users", id)
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
        util.debugLog(self, "GetUserFromToken: token: {}".format(token))
        tok = self.root['global']['tokens'][token]
        doc = tok.doc
        util.debugLog(self, "GetUserFromToken: doc: {}".format(pp.pformat(doc)))
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
        return self.root['app'].keys()

    def NewApplication(self, app_name):
        id = self.db['applications'].insert({'_class': "Application", "app_name": app_name})

        self.root['app'][app_name] = {
            "_doc": bson.DBRef("applications", id),
            "builds": {"_doc": self.parent.NewContainer("BuildContainer", "builds", app_name)},
            "action": {"_doc": self.parent.NewContainer("ActionContainer", "action", app_name)}
        }

    def DeleteApplication(self, app_name):
        self.parent.DeleteObject(self.root['app'], app_name, 'applications')

class JobDataService(GenericChildDataService):
    def GetAllActions(self, app_name):
        if 'action' in self.root['app'][app_name]:
            return [action for action in self.root['app'][app_name]['action'] if action[0] != '_']

    def NewJob(self, name):
        job = Job({
            'status': "running",
            'attributes': {
                'name': name
            }
        })
        jid = self.db['jobs'].insert({
            '_class': 'Job',
            'job_id': str(job.job_id),
            'status': job.status,
            'attributes': job.attribs
        })
        self.root['job'][str(job.job_id)] = {
            "_doc": bson.DBRef("jobs", jid)
        }
        return job

    def NewJobData(self, job_id, data):
        self.db['job_data'].insert({
            'job_id': job_id,
            'data': data
        })

    def GetJobs(self, active):
        return [d['job_id'] for d in self.db['jobs'].find({'status': 'running'} if active else {})]

    def GetJobData(self, job_id):
        return sorted([{'created_datetime': d['_id'].generation_time.isoformat(' '), 'data': d['data']} for
                       d in self.db['job_data'].find({'job_id': job_id})], key=lambda k: k['created_datetime'])

    def SaveJobResults(self, job_id, results):
        now = datetime.datetime.now(tz=pytz.utc)
        doc = self.db['jobs'].find_one({'job_id': job_id})
        diff = (now - doc['_id'].generation_time).total_seconds()
        res = self.db['jobs'].update({'job_id': job_id}, {'$set': {'status': "completed",
                                                                   'completed_datetime': now,
                                                                   'duration_in_seconds': diff}})
        util.debugLog(self, "SaveJobResults: update job doc: {}".format(res))
        self.NewJobData(job_id, {"completed_results": results})

    def NewAction(self, app_name, action_name, params):
        util.debugLog(self, "NewAction: app_name: {}".format(app_name))
        util.debugLog(self, "NewAction: action_name: {}".format(action_name))
        self.root['app'][app_name]['action'][action_name] = Action(app_name, action_name, params, self)
        pp = pprint.PrettyPrinter(indent=4)
        util.debugLog(self, "NewAction: actions: {}".format(pp.pformat(self.root['app'][app_name]['action'])))

    def ExecuteAction(self, app_name, action_name, params, verb):
        return self.parent.actionsvc.async(app_name, action_name, params, verb)

class ServerDataService(GenericChildDataService):
    def GetServers(self):
        return self.root['server'].keys()

    def NewServer(self, name, attribs):
        server = Server({
            'name': name,
            'attribues': attribs
        })
        sid = self.db['servers'].insert({
            'name': server.name,
            'gitdeploys': [],
            'attributes': server.attributes
        })
        self.root['server'][name] = {
            '_doc': bson.DBRef('servers', sid),
            'gitdeploys': {"_doc": self.parent.NewContainer("GitDeployContainer", "gitdeploys", name)}
        }

    def DeleteServer(self, name):
        self.parent.DeleteObject(self.root['server'], name, 'servers')

    def AddGitDeploy(self, server_name, gitdeploy_dbref):
        pass

    def GetGitDeploys(self, server_name):
        return self.root['server'][server_name]['gitdeploys'].keys()

class GitDeployDataService(GenericChildDataService):
    def NewGitDeploy(self, name, app_name, server_name, location, attributes):
        sid = self.db['servers'].find_one({'name': server_name})
        assert id is not None
        gd = GitDeploy({
            'name': name,
            'application': app_name,
            'server': bson.DBRef('servers', sid),
            'location': location,
            'attributes': attributes
        })
        gdid = self.db['gitdeploys'].insert({
            'name': gd.name,
            'applicadtion': gd.application,
            'server': gd.server,
            'attributes': gd.attributes,
            'location': gd.location
        })
        self.root['server'][server_name]['gitdeploys'][name] = {'_doc': bson.DBRef('gitdeploys', gdid)}

class DataService:
    def __init__(self, settings, db, root):
        self.settings = settings
        self.db = db
        self.root = root
        self.actionsvc = ActionService(self)   # potential reference cycles
        self.buildsvc = BuildDataService(self)
        self.usersvc = UserDataService(self)
        self.appsvc = ApplicationDataService(self)
        self.jobsvc = JobDataService(self)
        self.serversvc = ServerDataService(self)
        self.gitdeploysvc = GitDeployDataService(self)

    def NewContainer(self, class_name, name, parent):
        cdoc = self.db['containers'].insert({'_class': class_name,
                                         'name': name,
                                         'parent': parent})
        return bson.DBRef('containers', cdoc)

    def DeleteObject(self, container, key, collection):
        id = container[key].doc['_id']
        self.db[collection].remove({'_id': id})
        del container[key]

class SupportedFileType:
    TarGz = 'tar.gz'
    TarBz2 = 'tar.bz2'
    Zip = 'zip'
    types = [TarBz2, TarGz, Zip]


class GenericDataModel:
    default_values = {}

    def __init__(self, doc):
        self.set_defaults()
        if doc is not None:
            for k in doc:
                if k == '_id':
                    self.created_datetime = doc['_id'].generation_time
                elif k[0] != '_':
                    self.set_data(k, doc[k])
        self.process_values()

    def process_values(self):
        pass

    def set_defaults(self):
        for k in self.default_values:
            if not hasattr(self, k):
                setattr(self, k, self.default_values[k])

    def set_data(self, key, value):
        self._set_data(key, value)

    def _set_data(self, key, value):
        setattr(self, key, value)

class KeyPair(GenericDataModel):
    pass

class Server(GenericDataModel):
    pass

class GitDeploy(GenericDataModel):
    default_values = {
        'name': None,
        'application': None,
        'server': bson.DBRef("", None),
        'attributes': dict(),
        'location': {
            'path': None,
            'git_repo': bson.DBRef("", None),
            'default_branch': None,
            'current_branch': None,
            'current_rev': None
        }
    }

class Deployment(GenericDataModel):
    pass


class Build(GenericDataModel):
    default_values = {
        'files': list(),
        'stored': False,
        'master_file': None,
        'packages': dict(),
        'attributes': dict()
    }


class Action:
    def __init__(self, app_name, action_name, params, datasvc):
        self.app_name = app_name
        self.action_name = action_name
        self.params = params
        self.datasvc = datasvc

    def execute(self, params, verb):
        return self.datasvc.ExecuteAction(self.app_name, self.action_name, params, verb)

class Application(GenericDataModel):
    pass

class User(GenericDataModel):
    default_values = {
        'password': None,
        'hashed_pw': None,
        'salt': None,
        'attributes': dict()
    }

    def process_values(self):
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

class Token(GenericDataModel):
    default_values = {
        'username': None,
        'token': None
    }

    def process_values(self):
        self.token = base64.urlsafe_b64encode(hashlib.sha256(uuid.uuid4().bytes).hexdigest())[:-2] \
            if self.token is None else self.token

class Job(GenericDataModel):
    default_values = {
        'status': 'running',
        'completed_datetime': None,
        'duration_in_seconds': None,
        'attributes': None,
        'job_id': None
    }

    def process_values(self):
        self.job_id = uuid.uuid4() if self.job_id is None else self.job_id


class GenericContainer:
    def __init__(self, name, parent, created_datetime):
        self.name = name
        self.parent = parent
        self.created_datetime = created_datetime

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

class GitDeployContainer(GenericContainer):
    pass

class DeploymentContainer(GenericContainer):
    pass

class KeyPairContainer(GenericContainer):
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
        #util.debugLog(self, "__getitem__: key: {}".format(key))
        key = self.__keytransform__(key)
        if self.is_action():
            #util.debugLog(self, "__getitem__: is_application: subtree: {}".format(self.tree[key]))
            return self.tree[key]
        if key in self.tree:
            doc = self.db.dereference(self.tree[key]['_doc'])
            if doc is None:
                #util.debugLog(self, "__getitem__: doc is none")
                raise KeyError
            #util.debugLog(self, "__getitem__: returning subtree")
            return RootTree(self.db, self.updater, self.tree[key], doc)
        else:
            #util.debugLog(self, "__getitem__: key not found in tree ")
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
    def __init__(self, tree, db):
        self.tree = tree
        self.db = db

    def clean_actions(self):
        #actions can't be serialized into mongo
        for a in self.tree['app']:
            actions = list()
            if a[0] != '_':
                if "action" in self.tree['app'][a]:
                    for ac in self.tree['app'][a]['action']:
                        if ac[0] != '_':
                            actions.append(ac)
                    for action in actions:
                        del self.tree['app'][a]['action'][action]

    def update(self):
        self.clean_actions()
        root_tree = self.db['root_tree'].find_one()
        self.db['root_tree'].update({"_id": root_tree['_id']}, self.tree)

class DataValidator:
    '''Independed class to migrate/validate the root tree and potentially all docs
        Intended to run prior to main application, to migrate schema or fix problems
    '''
    def __init__(self, root, db):
        self.root = root
        self.db = db

    def run(self):
        util.debugLog(self, "running")
        self.check_root()
        self.check_toplevel()
        self.check_apps()
        self.check_jobs()
        self.check_servers()
        self.check_deployments()
        self.SaveRoot()

    def SaveRoot(self):
        self.db['root_tree'].update({"_id": self.root['_id']}, self.root)

    def NewContainer(self, class_name, name, parent):
        cdoc = self.db['containers'].insert({'_class': class_name,
                                         'name': name,
                                         'parent': parent})
        return bson.DBRef('containers', cdoc)

    def check_jobs(self):
        djs = list()
        for j in self.root['job']:
            if j[0] != '_':
                if self.db.dereference(self.root['job'][j]['_doc']) is None:
                    util.debugLog(self, "WARNING: found dangling job ref in root tree: {}; deleting".format(j))
                    djs.append(j)
        for j in djs:
            del self.root['job'][j]

    def check_apps(self):
        for a in self.root['app']:
            if a[0] != '_':
                if 'builds' not in self.root['app'][a]:
                    util.debugLog(self, "WARNING: 'builds' not found under {}".format(a))
                    self.root['app'][a]['builds'] = dict()
                    self.root['app'][a]['builds']['_doc'] = self.NewContainer("BuildContainer", "builds", a)
                if 'action' not in self.root['app'][a]:
                    util.debugLog(self, "WARNING: 'action' not found under {}".format(a))
                    self.root['app'][a]['action'] = dict()
                    self.root['app'][a]['action']['_doc'] = self.NewContainer("ActionContainer", "action", a)

    def check_servers(self):
        for s in self.root['server']:
            if s[0] != '_':
                if 'gitdeploys' not in self.root['server'][s]:
                    util.debugLog(self, "WARNING: 'gitdeploys' not found under server {}".format(s))
                    self.root['server'][s]['gitdeploy'] = dict()
                    self.root['server'][s]['gitdeploy']['_doc'] = self.NewContainer("GitDeployContainer",
                                                                                    "gitdeploys", s)
    def check_deployments(self):
        for d in self.root['deployment']:
            if d[0] != '_':
                pass

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
            },
            'deployment': {
                'class': 'DeploymentContainer'
            },
            'keypair': {
                'class': 'KeyPairContainer'
            }
        }
        for tl in top_levels:
            if tl not in self.root:
                util.debugLog(self, "WARNING: '{}' not found under root".format(tl))
                self.root[tl] = dict()
                self.root[tl]['_doc'] = self.NewContainer(top_levels[tl]['class'], tl, "")

    def check_root(self):
        self.root = dict() if self.root is None else self.root
