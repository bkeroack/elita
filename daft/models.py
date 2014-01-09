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

import daft
import util
import salt_control
import keypair
import daft_exceptions
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

class Request:
    db = None

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
        self.parent.refresh_root()
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
        self.parent.refresh_root()
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

    def NewApplication(self, app_name):
        id = self.db['applications'].insert({'_class': "Application", "app_name": app_name})
        self.parent.refresh_root()
        self.root['app'][app_name] = {
            "_doc": bson.DBRef("applications", id),
            "builds": {"_doc": self.parent.NewContainer("BuildContainer", "builds", app_name)},
            "action": {"_doc": self.parent.NewContainer("ActionContainer", "action", app_name)},
            "gitrepos": {"_doc": self.parent.NewContainer("GitRepoContainer", "gitrepos", app_name)}
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
            'attributes': job.attributes
        })
        self.parent.refresh_root()
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
        self.parent.refresh_root()
        self.root['app'][app_name]['action'][action_name] = Action(app_name, action_name, params, self)
        pp = pprint.PrettyPrinter(indent=4)
        util.debugLog(self, "NewAction: actions: {}".format(pp.pformat(self.root['app'][app_name]['action'])))

    def ExecuteAction(self, app_name, action_name, params, verb):
        return self.parent.actionsvc.async(app_name, action_name, params, verb)

class ServerDataService(GenericChildDataService):
    def GetServers(self):
        return [k for k in self.root['server'].keys() if k[0] != '_']

    def NewServer(self, name, attribs, existing=False):
        try:
            server = Server({
                'name': name,
                'attributes': attribs
            })
        except daft_exceptions.SaltServerNotAccessible:
            return {
                'NewServer': {
                    'status': 'error',
                    'message': "server not accessible via salt"
                }
            }
        sid = self.db['servers'].insert({
            '_class': "Server",
            'name': server.name,
            'gitdeploys': [],
            'attributes': server.attributes
        })
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

    def DeleteServer(self, name):
        self.parent.DeleteObject(self.root['server'], name, 'servers')

    def AddGitDeploy(self, server_name, gitdeploy_dbref):
        pass

    def GetGitDeploys(self, server_name):
        return [k for k in self.root['server'][server_name]['gitdeploys'].keys() if k[0] != '_']

class GitDataService(GenericChildDataService):
    def NewGitDeploy(self, name, app_name, server_name, location, attributes):
        server_doc = self.db['servers'].find_one({'name': server_name})
        if server_doc is None:
            return {'NewGitDeploy': "invalid server (not found)"}
        gitrepo_doc = self.db['gitrepos'].find_one({name: location['gitrepo']})
        if gitrepo_doc is None:
            return {'NewGitDeploy': "invalid gitrepo (not found)"}
        location['gitrepo'] = bson.DBRef("gitrepos", gitrepo_doc['_id'])
        gd = GitDeploy({
            'name': name,
            'application': app_name,
            'server': bson.DBRef('servers', server_doc['_id']),
            'location': location,
            'attributes': attributes
        })
        gdid = self.db['gitdeploys'].insert({
            '_class': "GitDeploy",
            'name': gd.name,
            'application': gd.application,
            'server': gd.server,
            'attributes': gd.attributes,
            'location': gd.location
        })
        self.parent.refresh_root()
        self.root['server'][server_name]['gitdeploys'][name] = {'_doc': bson.DBRef('gitdeploys', gdid)}

    def GetGitProviders(self, objs=False):
        if objs:
            return [GitProvider(gp.doc) for gp in self.root['global']['gitproviders']]
        return [k for k in self.root['global']['gitproviders'].keys() if k[0] != '_']

    def GetGitProvider(self, name):
        doc = self.db['gitproviders'].find_one({'name': name})
        return {k: doc[k] for k in doc if k[0] != '_'}

    def NewGitProvider(self, name, type, auth):
        if name in self.root['global']['gitproviders']:
            self.db['gitproviders'].remove({'name': name})
        gpobj = GitProvider({
            'name': name,
            'type': type,
            'auth': auth
        })
        gpid = self.db['gitproviders'].insert({
            '_class': "GitProvider",
            'name': gpobj.name,
            'type': gpobj.type,
            'base_url': gpobj.base_url,
            'auth': gpobj.auth
        })
        self.parent.refresh_root()
        self.root['global']['gitproviders'][gpobj.name] = {'_doc': bson.DBRef('gitproviders', gpid)}

    def UpdateGitProvider(self, name, doc):
        self.parent.UpdateObject(name, doc, 'gitproviders', GitProvider)

    def DeleteGitProvider(self, name):
        self.parent.DeleteObject(self.root['global']['gitproviders'], name, 'gitproviders')

    def GetGitRepos(self, app):
        return [k for k in self.root['app'][app]['gitrepos'].keys() if k[0] != '_']

    def NewGitRepo(self, app, name, keypair, gitprovider, existing=False):
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
            'gitprovider': bson.DBRef("gitproviders", gp_doc['_id'])
        })
        gr_id = self.db['gitrepos'].insert({
            '_class': "GitRepo",
            'name': gr_obj.name,
            'application': gr_obj.application,
            'keypair': gr_obj.keypair,
            'gitprovider': gr_obj.gitprovider
        })
        self.parent.refresh_root()
        self.root['app'][app]['gitrepos'][name] = {
            '_doc': bson.DBRef('gitrepos', gr_id)
        }
        return {'NewGitRepo': 'ok'}

    def DeleteGitRepo(self, name):
        self.parent.DeleteObject(self.root['global']['gitrepos'], name, 'gitrepos')

class KeyDataService(GenericChildDataService):
    def GetKeyPairs(self):
        return [k for k in self.root['global']['keypairs'].keys() if k[0] != '_']

    def GetKeyPair(self, name):
        kobj = KeyPair(self.db['keypairs'].find_one({'name': name}))
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
            util.debugLog(self, "exception: {}, {}".format(exc_type, exc_obj))
            if exc_type == daft_exceptions.InvalidPrivateKey:
                err = "Invalid private key"
            if exc_type == daft_exceptions.InvalidPublicKey:
                err = "Invalid public key"
            else:
                err = "unknown key error"
            return {
                'NewKeyPair': {
                    'status': "error",
                    'message': err
                }
            }
        kp_id = self.db['keypairs'].insert({
            'name': kp_obj.name,
            'attributes': kp_obj.attributes,
            'key_type': kp_obj.key_type,
            'private_key': kp_obj.private_key,
            'public_key': kp_obj.public_key
        })
        self.root['global']['keypairs'][kp_obj.name] = {
            '_doc': bson.DBRef("keypairs", kp_id)
        }
        return {
            'NewKeyPair': {
                'status': 'ok'
            }
        }

    def UpdateKeyPair(self, name, doc):
        self.parent.UpdateObject(name, doc, "keypairs", KeyPair)

    def DeleteKeyPair(self, name):
        self.parent.DeleteObject(self.root['global']['keypairs'], name, "keypairs")


class DataService:
    def __init__(self, settings, db, root, actions_init=True):
        self.settings = settings
        self.db = db
        self.root = root
        # potential reference cycles
        self.buildsvc = BuildDataService(self)
        self.usersvc = UserDataService(self)
        self.appsvc = ApplicationDataService(self)
        self.jobsvc = JobDataService(self)
        self.serversvc = ServerDataService(self)
        self.gitsvc = GitDataService(self)
        self.keysvc = KeyDataService(self)
        if actions_init:
            self.actionsvc = ActionService(self)

    def refresh_root(self):
        # when running long async actions the root tree passed to constructor may be stale by the time we try to update
        # so just prior to altering it, we refresh from the DB
        req = Request()
        req.db = self.db
        self.root = daft.RootService(req)

    def UpdateObject(self, name, doc, collection_name, class_obj):
        old_doc = self.db[collection_name].find_one({"name": name})
        if old_doc:
            cobj = class_obj(old_doc)
            cobj.update_values(doc)
            new_doc = cobj.get_doc()
            new_doc['_id'] = old_doc['_id']
            new_doc['class'] = class_obj.__class__.__name__
            self.db[collection_name].save(new_doc)

    def NewContainer(self, class_name, name, parent):
        cdoc = self.db['containers'].insert({'_class': class_name,
                                         'name': name,
                                         'parent': parent})
        return bson.DBRef('containers', cdoc)

    def DeleteObject(self, container, key, collection):
        id = container[key].doc['_id']
        self.db[collection].remove({'_id': id})
        self.parent.refresh_root()
        del container[key]

    def Dereference(self, dbref):
        return self.db.dereference(dbref)

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
            raise daft_exceptions.InvalidKeyPairType
        kp = keypair.KeyPair(self.private_key, self.public_key)
        try:
            kp.verify_public()
        except:
            raise daft_exceptions.InvalidPublicKey
        try:
            kp.verify_private()
        except:
            raise daft_exceptions.InvalidPrivateKey

class Server(GenericDataModel):
    default_values = {
        "name": None,
        "server_type": None,
        "attributes": dict(),
        "gitdeploys": [bson.DBRef("", None)],
        "salt_key": bson.DBRef("", None)
    }

    def init_hook(self):
        sc = salt_control.SaltController(self.name)
        if not sc.verify_connectivity():
            raise daft_exceptions.SaltServerNotAccessible

class GitProvider(GenericDataModel):
    default_values = {
        'name': None,
        'type': None,
        'base_url': None,
        'auth': {
            'username': None,
            'password': None
        }
    }

class GitRepo(GenericDataModel):
    default_values = {
        'name': None,
        'application': None,
        'keypair': bson.DBRef("", None),
        'gitprovider': bson.DBRef("", None)
    }

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
        'build_name': None,
        'app_name': None,
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
        return self.datasvc.jobsvc.ExecuteAction(self.app_name, self.action_name, params, verb)

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
        'completed_datetime': None,
        'duration_in_seconds': None,
        'attributes': None,
        'job_id': None
    }

    def init_hook(self):
        self.job_id = uuid.uuid4() if self.job_id is None else self.job_id

class GenericContainer:
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
            if key == '_doc':
                return self.tree[key]
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
    '''Independent class to migrate/validate the root tree and potentially all docs
        Intended to run prior to main application, to migrate schema or fix problems
    '''
    def __init__(self, root, db):
        self.root = root
        self.db = db

    def run(self):
        util.debugLog(self, "running")
        self.check_root()
        self.check_doc_consistency()
        self.check_toplevel()
        self.check_global()
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
            'users'
        ]
        for c in collects:
            for d in self.db[c].find():
                if '_class' not in d:
                    util.debugLog(self, "WARNING: class specification not found in object {} from collection {}"
                    .format(d['_id'], c))
                    util.debugLog(self, "...deleting malformed object")
                    self.db[c].remove({'_id': d['_id']})
                if c == 'applications':
                    if d['app_name'] not in self.root['app']:
                        util.debugLog(self, "WARNING: orphan application object: '{}', adding to root tree".format(d['app_name']))
                        self.root['app'][d['app_name']] = {'_doc': bson.DBRef('applications', d['_id'])}
                if c == 'builds':
                    if d['build_name'] not in self.root['app'][d['app_name']]['builds']:
                        util.debugLog(self, "WARNING: orphan build object: '{}/{}', adding to root tree".format(d['app_name'], d['build_name']))
                        self.root['app'][d['app_name']]['builds'][d['build_name']] = {'_doc': bson.DBRef('builds', d['_id'])}
                if c == 'gitproviders':
                    if d['name'] not in self.root['global']['gitproviders']:
                        util.debugLog(self, "WARNING: orphan gitprovider object: '{}', adding to root tree".format(d['name']))
                        self.root['global']['gitproviders'][d['name']] = {'_doc': bson.DBRef('gitproviders', d['_id'])}
                if c == 'gitrepos':
                    if d['name'] not in self.root['app'][d['application']]['gitrepos']:
                        util.debugLog(self, "WARNING: orphan gitrepo object: '{}/{}', adding to root tree".format(d['application'], d['name']))
                        self.root['app'][d['application']]['gitrepo'][d['name']] = {'_doc': bson.DBRef('gitrepos', d['_id'])}
                if c == 'gitdeploys':
                    if d['name'] not in self.root['app'][d['application']]['gitdeploys']:
                        util.debugLog(self, "WARNING: orphan gitdeploy object: '{}/{}', adding to root tree".format(d['application'], d['name']))
                        self.root['app'][d['application']]['gitdeploys'][d['name']] = {'_doc': bson.DBRef('gitdeploys', d['_id'])}
                if c == 'jobs':
                    if d['job_id'] not in self.root['job']:
                        util.debugLog(self, "WARNING: orphan job object: '{}', adding to root tree".format(d['job_id']))
                        self.root['job'][d['job_id']] = {'_doc': bson.DBRef('jobs', d['_id'])}
                if c == 'tokens':
                    if d['token'] not in self.root['global']['tokens']:
                        util.debugLog(self, "WARNING: orphan token object: '{}', adding to root tree".format(d['token']))
                        self.root['global']['tokens'][d['token']] = {'_doc': bson.DBRef('tokens', d['_id'])}
                if c == 'users':
                    if d['name'] not in self.root['global']['users']:
                        util.debugLog(self, "WARNING: orphan user object: '{}', adding to root tree".format(d['name']))
                        self.root['global']['users'][d['name']] = {'_doc': bson.DBRef('users', d['_id'])}


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
                util.debugLog(self, "WARNING: '{}' not found under global".format(l))
                self.root['global'][l] = dict()
                self.root['global'][l]['_doc'] = self.NewContainer(global_levels[l]['class'], l, "")

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
        app_sublevels = {
            'builds': {
                'class': "BuildContainer"
            },
            'action': {
                'class': "ActionContainer"
            },
            'gitrepos': {
                'class': "GitRepoContainer"
            }
        }
        for a in self.root['app']:
            if a[0] != '_':
                for sl in app_sublevels:
                    if sl not in self.root['app'][a]:
                        util.debugLog(self, "WARNING: '{}' not found under {}".format(sl, a))
                        self.root['app'][a][sl] = dict()
                        self.root['app'][a][sl]['_doc'] = self.NewContainer(app_sublevels[sl]['class'], sl, a)

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
