import collections
import hashlib
import uuid
import base64
import os.path
import shutil
import bson
import pymongo
import pprint

import util
import daft_config
import action as daft_action

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
    def __init__(self, db):
        self.db = db
        self.root = RootTree(db, db['root_tree'].find_one(), None)
        self.actionsvc = daft_action.ActionService(self)   # potential reference cycle

        self.ListAllActions()  # debugging

    def ListAllActions(self):
        for a in self.root['app']:
            if a[0] != '_':
                util.debugLog(self, "ListAllActions: {}".format(a))
                if 'action' in self.root['app'][a]:
                    util.debugLog(self, "...actions: {}".format(self.root['app'][a]['action']))

    def NewContainer(self, class_name, name, parent):
        cdoc = self.db['containers'].insert({'_class': class_name,
                                         'name': name,
                                         'parent': parent})
        return bson.DBRef('containers', cdoc['_id'])

    def Builds(self, app_name):
        return self.root['app'][app_name]['builds']

    def Applications(self):
        return self.root['app']

    def NewAction(self, app_name, action_name, params, callable):
        util.debugLog(self, "NewAction: app_name: {}".format(app_name))
        util.debugLog(self, "NewAction: action_name: {}".format(action_name))
        if 'action' not in self.root['app'][app_name]:
            self.root['app'][app_name]['action'] = dict()
        self.root['app'][app_name]['action'][action_name] = Action(app_name, action_name, params, callable)
        pp = pprint.PrettyPrinter(indent=4)
        util.debugLog(self, "NewAction: actions: {}".format(pp.pformat(self.root['app'][app_name]['action'])))

    def NewBuild(self, app_name, build_name, attribs, subsys):
        id = self.db['builds'].insert({'build_name': build_name,
                                       'files': [],
                                       'stored': False,
                                       'app_name': app_name,
                                       'packages': [],
                                       'attributes': attribs,
                                       'subsys': subsys})
        self.root['app'][app_name]['builds'][build_name] = {
            "_doc": bson.DBRef("builds", id)
        }

    def NewToken(self, username):
        token = Token(username)
        id = self.db['tokens'].insert({
            'username': username,
            'token': token.token,
            '_class': "Token"
        })
        self.root['global']['tokens'][token.token] = {
            "_doc": bson.DBRef("tokens", id)
        }
        return token

    def DeleteBuild(self, app_name, build_name):
        pass

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

    def DeleteApplication(self, app_name):
        pass

    def GetUsers(self):
        return self.root['global']['users'].keys()

    def GetUser(self, username):
        return self.root['global']['users'][username]

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
    def __init__(self, app_name, build_name, attributes={}, subsys=[]):
        self.app_name = app_name
        self.build_name = build_name
        self.attributes = attributes
        self.subsys = subsys
        self.stored = False
        self.files = dict()  # { filename: filetype }
        self.master_file = None  # original uploaded file
        self.packages = dict()  # { package_type: {'filename': filename, 'file_type': file_type}}

class BuildDetail:
    def __init__(self, buildobj):
        self.buildobj = buildobj

class BuildContainer:
    def __init__(self, app_name):
        self.app_name = app_name

    def remove_build(self, buildname):
        dir = daft_config.DaftConfiguration().get_build_dir()
        path = "{root_dir}/{app}/{build}".format(root_dir=dir, app=self.app_name, build=buildname)
        util.debugLog(self, "remove_build: path: {}".format(path))
        if os.path.isdir(path):
            util.debugLog(self, "remove_build: deleting")
            shutil.rmtree(path)
        del self[buildname]

class Subsystem:
    def __init__(self, app_name):
        self.app_name = app_name

class SubsystemContainer:
    def __init__(self, app_name):
        self.app_name = app_name

class Action:
    def __init__(self, app_name, action_name, params, callable):
        self.app_name = app_name
        self.action_name = action_name
        self.params = params
        self.callable = callable

    def execute(self, params, verb):
        return self.callable(DataService()).start(params, verb)

class ActionContainer:
    def __init__(self, app_name):
        self.app_name = app_name

class Application:
    def __init__(self, app_name):
        self.app_name = app_name

class User:
    def __init__(self, name, permissions, hashed_pw, salt, attributes={}):
        util.debugLog(self, "user: {}".format(name))
        self.salt = salt
        util.debugLog(self, "got salt: {}".format(self.salt))
        self.name = name
        self.hashed_pw = hashed_pw
        util.debugLog(self, "hashed pw: {}".format(self.hashed_pw))
        self.permissions = permissions
        self.attributes = attributes

    def hash_pw(self, pw):
        return base64.urlsafe_b64encode(hashlib.sha512(pw + self.salt).hexdigest())

    def validate_password(self, pw):
        return self.hashed_pw == self.hash_pw(pw)

    def change_password(self, new_pw):
        self.hashed_pw = self.hash_pw(new_pw)

class UserContainer:
    def __init__(self):
        self.salt = base64.urlsafe_b64encode((uuid.uuid4().bytes))

class TokenContainer:
    def __init__(self):
        pass

class Token:
    def __init__(self, username, token=None):
        self.username = username
        self.token = base64.urlsafe_b64encode(hashlib.sha256(uuid.uuid4().bytes).hexdigest())[:-2] \
            if token is None else token

class ApplicationContainer:
    pass

class GlobalContainer:
    pass



class RootTree(collections.MutableMapping):
    def __init__(self, db, tree, doc, *args, **kwargs):
        self.pp = pprint.PrettyPrinter(indent=4)
        self.db = db
        self.tree = tree
        self.doc = doc

    def is_application(self, key):
        return self.doc is not None and self.doc['_class'] == 'Application' and key == 'action'

    def __getitem__(self, key):
        #util.debugLog(self, "__getitem__: key: {}; self.doc: {}".format(key, self.doc))
        key = self.__keytransform__(key)
        if self.is_application(key):
            #util.debugLog(self, "__getitem__: is application")
            return self.tree[key]
        if key in self.tree:
            doc = self.db.dereference(self.tree[key]['_doc'])
            if doc is None:
                raise KeyError
            return RootTree(self.db, self.tree[key], doc)
        else:
            raise KeyError

    def __setitem__(self, key, value):
        #util.debugLog(self, "__setitem__: key: {}; value: {}; self.doc: {}".format(key, value, self.doc))
        root_tree = self.db['root_tree'].find_one()
        #there's only a few legal places for dynamic tree insertion
        if self.is_application(key):     # dynamically populated each request
            #util.debugLog(self, "is_application: true")
            self.tree[key] = value
            #util.debugLog(self, "__setitem__: self.tree: {}".format(self.pp.pformat(self.tree)))
            return
        if self.doc['_class'] == "AppContainer":
            root_tree['app'][key] = value
        if self.doc['_class'] == "UserContainer":
            root_tree['global']['users'][key] = value
        if self.doc['_class'] == "TokenContainer":
            root_tree['global']['tokens'][key] = value
        if self.doc['_class'] == "BuildContainer":
            root_tree['app'][self.doc['parent']]['builds'][key] = value
        else:
            raise ValueError
        self.db['root_tree'].update({"_id": root_tree['_id']}, root_tree)

    def __delitem__(self, key):
        #unimplmented
        return

    def __iter__(self):
        return iter(self.tree)

    def __len__(self):
        return len(self.tree)

    def __keytransform__(self, key):
        return key

def appmaker(db):
    return RootTree(db, db['root_tree'].find_one(), None)
