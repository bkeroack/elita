import collections
import hashlib
import uuid
import base64
import os.path
import shutil
import bson
import pprint

import util
import daft_config
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


class DataService:
    def __init__(self, mdbinfo, db, root):
        self.mdbinfo = mdbinfo
        self.db = db
        self.root = root
        self.actionsvc = ActionService(self)   # potential reference cycle


    def GetAllActions(self, app_name):
        if 'action' in self.root['app'][app_name]:
            return [action for action in self.root['app'][app_name]['action'] if action[0] != '_']

    def NewContainer(self, class_name, name, parent):
        cdoc = self.db['containers'].insert({'_class': class_name,
                                         'name': name,
                                         'parent': parent})
        return bson.DBRef('containers', cdoc)

    def GetBuilds(self, app_name):
        return [k for k in self.root['app'][app_name]['builds'].keys() if k[0] != '_']

    def Applications(self):
        return self.root['app'].keys()

    def NewJob(self, name):
        job = Job(None, "running", None, attributes={'name': name})
        jid = self.db['jobs'].insert({
            '_class': 'Job',
            'job_id': str(job.id),
            'status': job.status,
            'attributes': job.attribs
        })
        self.root['job'][str(job.id)] = {
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
        res = self.db['jobs'].update({'job_id': job_id}, {'$set': {'status': "completed"}})
        print(res)
        util.debugLog(self, "SaveJobResults: update job doc: {}".format(res))
        self.NewJobData(job_id, {"completed_results": results})

    def NewAction(self, app_name, action_name, params):
        util.debugLog(self, "NewAction: app_name: {}".format(app_name))
        util.debugLog(self, "NewAction: action_name: {}".format(action_name))
        self.root['app'][app_name]['action'][action_name] = Action(app_name, action_name, params, self)
        pp = pprint.PrettyPrinter(indent=4)
        util.debugLog(self, "NewAction: actions: {}".format(pp.pformat(self.root['app'][app_name]['action'])))

    def ExecuteAction(self, app_name, action_name, params, verb):
        return self.actionsvc.async(app_name, action_name, params, verb)

    def NewBuild(self, app_name, build_name, attribs, subsys):
        buildobj = Build(app_name, build_name, None, attributes=attribs, subsys=subsys)
        id = self.db['builds'].insert({'_class': "Build",
                                       'build_name': buildobj.build_name,
                                       'files': buildobj.files,
                                       'stored': buildobj.stored,
                                       'app_name': buildobj.app_name,
                                       'packages': buildobj.packages,
                                       'attributes': buildobj.attributes,
                                       'subsys': buildobj.subsys})
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

    def NewToken(self, username):
        token = Token(username, None)
        id = self.db['tokens'].insert({
            'username': username,
            'token': token.token,
            '_class': "Token"
        })
        self.root['global']['tokens'][token.token] = {
            "_doc": bson.DBRef("tokens", id)
        }
        return token

    def NewUser(self, name, pw, perms, attribs):
        userobj = User(name, perms, None, password=pw, attributes=attribs)
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

    def DeleteObject(self, container, key, collection):
        id = container[key].doc['_id']
        self.db[collection].remove({'_id': id})
        del container[key]

    def DeleteUser(self, name):
        self.DeleteObject(self.root['global']['users'], name, "users")

    def DeleteBuildStorage(self, app_name, build_name):
        dir = daft_config.DaftConfiguration().get_build_dir()
        path = "{root_dir}/{app}/{build}".format(root_dir=dir, app=app_name, build=build_name)
        util.debugLog(self, "DeleteBuildStorage: path: {}".format(path))
        if os.path.isdir(path):
            util.debugLog(self, "DeleteBuildStorage: remove_build: deleting")
            shutil.rmtree(path)

    def DeleteBuild(self, app_name, build_name):
        self.DeleteBuildStorage(app_name, build_name)
        self.DeleteObject(self.root['app'][app_name]['builds'], build_name, "builds")

    def DeleteToken(self, token):
        self.DeleteObject(self.root['global']['tokens'], token, "tokens")

    def NewApplication(self, app_name):

        id = self.db['applications'].insert({'_class': "Application", "app_name": app_name})

        self.root['app'][app_name] = {
            "_doc": bson.DBRef("applications", id),
            "environments": {"_doc": self.NewContainer("EnvironmentContainer", "evironments", app_name)},
            "builds": {"_doc": self.NewContainer("BuildContainer", "builds", app_name)},
            "subsys": {"_doc": self.NewContainer("SubsystemContainer", "subsystems", app_name)},
            "action": {"_doc": self.NewContainer("ActionContainer", "action", app_name)}
        }

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

    def DeleteApplication(self, app_name):
        self.DeleteObject(self.root['app'], app_name, 'applications')

    def GetUsers(self):
        return [k for k in self.root['global']['users'].keys() if k[0] != '_']

    def GetUser(self, username):
        return self.PopulateObject(self.root['global']['users'][username].doc, User)

    def GetBuild(self, app_name, build_name):
        return self.PopulateObject(self.root['app'][app_name]['builds'][build_name].doc, Build)

    def PopulateObject(self, doc, class_obj):
        #generate model object from mongo doc
        #pp = pprint.PrettyPrinter(indent=4)
        #util.debugLog(self, "PopulateObject: doc: {}".format(pp.pformat(doc)))
        args = {k: doc[k] for k in doc if k[0] != u'_'}
        args['created_datetime'] = doc['_id'].generation_time
        return class_obj(**args)

    def SaveUser(self, userobj):
        #find and update user document
        doc = self.db['users'].find_one({"name": userobj.name})
        assert doc is not None
        doc['hashed_pw'] = userobj.hashed_pw
        doc['attributes'] = userobj.attributes
        doc['salt'] = userobj.salt
        doc['permissions'] = userobj.permissions
        self.db['users'].update({"_id": doc["_id"]}, doc)

class SupportedFileType:
    TarGz = 'tar.gz'
    TarBz2 = 'tar.bz2'
    Zip = 'zip'
    types = [TarBz2, TarGz, Zip]


class GenericContainer:
    def __init__(self, name, parent, created_datetime):
        self.name = name
        self.parent = parent
        self.created_datetime = created_datetime

class Server:
    env_name = None

class Deployment:
    env_name = None

class Environment:
    app_name = None

class EnvironmentContainer:
    def __init__(self, app_name):
        self.app_name = app_name

class Build:
    def __init__(self, app_name, build_name, created_datetime, files=list(), master_file=None, packages=dict(),
                 stored=False, attributes={}, subsys=[]):
        self.app_name = app_name
        self.created_datetime = created_datetime
        self.build_name = build_name
        self.attributes = attributes
        self.subsys = subsys
        self.stored = stored
        self.files = files  # { filename: filetype }
        self.master_file = master_file  # original uploaded file
        self.packages = packages  # { package_type: {'filename': filename, 'file_type': file_type}}

class Subsystem:
    def __init__(self, app_name):
        self.app_name = app_name

class SubsystemContainer:
    def __init__(self, app_name):
        self.app_name = app_name

class Action:
    def __init__(self, app_name, action_name, params, datasvc):
        self.app_name = app_name
        self.action_name = action_name
        self.params = params
        self.datasvc = datasvc

    def execute(self, params, verb):
        return self.datasvc.ExecuteAction(self.app_name, self.action_name, params, verb)

class Application:
    def __init__(self, app_name, created_datetime):
        self.app_name = app_name
        self.created_datetime = created_datetime

class User:
    def __init__(self, name, permissions, created_datetime, password=None, hashed_pw=None, salt=None, attributes={}):
        util.debugLog(self, "user: {}".format(name))
        self.salt = base64.urlsafe_b64encode(uuid.uuid4().bytes) if salt is None else salt
        util.debugLog(self, "got salt: {}".format(self.salt))
        self.name = name
        self.hashed_pw = hashed_pw if hashed_pw is not None else self.hash_pw(password)
        util.debugLog(self, "hashed pw: {}".format(self.hashed_pw))
        self.permissions = permissions
        self.attributes = attributes
        self.created_datetime = created_datetime

    def hash_pw(self, pw):
        assert pw is not None
        return base64.urlsafe_b64encode(hashlib.sha512(pw + self.salt).hexdigest())

    def validate_password(self, pw):
        return self.hashed_pw == self.hash_pw(pw)

    def change_password(self, new_pw):
        self.hashed_pw = self.hash_pw(new_pw)

class Token:
    def __init__(self, username, created_datetime, token=None):
        self.username = username
        self.created_datetime = created_datetime
        self.token = base64.urlsafe_b64encode(hashlib.sha256(uuid.uuid4().bytes).hexdigest())[:-2] \
            if token is None else token

class Job:
    def __init__(self, job_id, status, created_datetime, attributes=None):
        self.id = uuid.uuid4() if job_id is None else job_id
        self.status = status
        self.attribs = attributes
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
        self.check_toplevel()
        self.check_apps()
        self.check_jobs()
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

    def check_toplevel(self):
        if 'app' not in self.root:
            util.debugLog(self, "WARNING: 'app' not found under root")
            self.root['app'] = dict()
            self.root['app']['_doc'] = self.NewContainer("ApplicationContainer", "app", "")
        if 'global' not in self.root:
            util.debugLog(self, "WARNING: 'global' not found under root")
            self.root['global'] = dict()
            self.root['global']['_doc'] = self.NewContainer("GlobalContainer", "global", "")
        if 'job' not in self.root:
            util.debugLog(self, "WARNING: 'job' not found under root")
            self.root['job'] = dict()
            self.root['job']['_doc'] = self.NewContainer("JobContainer", "job", "")
