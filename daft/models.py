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
    def __init__(self, db, root):
        self.db = db
        self.root = root
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

    def GetBuilds(self, app_name):
        return self.root['app'][app_name]['builds'].keys()

    def Applications(self):
        return self.root['app'].keys()

    def NewAction(self, app_name, action_name, params, callable):
        util.debugLog(self, "NewAction: app_name: {}".format(app_name))
        util.debugLog(self, "NewAction: action_name: {}".format(action_name))
        if 'action' not in self.root['app'][app_name]:
            self.root['app'][app_name]['action'] = dict()
        self.root['app'][app_name]['action'][action_name] = Action(app_name, action_name, params, callable)
        pp = pprint.PrettyPrinter(indent=4)
        util.debugLog(self, "NewAction: actions: {}".format(pp.pformat(self.root['app'][app_name]['action'])))

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

    def DeleteBuild(self, app_name, build_name):
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
        return self.root['global']['tokens'].keys()

    def DeleteApplication(self, app_name):
        self.DeleteObject(self.root['app'], app_name, 'applications')

    def GetUsers(self):
        return self.root['global']['users'].keys()

    def GetUser(self, username):
        return self.PopulateObject(self.root['global']['users'][username].doc, User)

    def PopulateObject(self, doc, class_obj):
        #generate model object from mongo doc
        pp = pprint.PrettyPrinter(indent=4)
        util.debugLog(self, "PopulateObject: doc: {}".format(pp.pformat(doc)))
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
    def __init__(self, app_name, action_name, params, callable):
        self.app_name = app_name
        self.action_name = action_name
        self.params = params
        self.callable = callable

    def execute(self, params, verb):
        return self.callable(DataService()).start(params, verb)

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



class RootTree(collections.MutableMapping):
    def __init__(self, db, updater, tree, doc, *args, **kwargs):
        self.pp = pprint.PrettyPrinter(indent=4)
        self.db = db
        self.tree = tree
        self.doc = doc
        self.updater = updater

    def is_application(self, key):
        return self.doc is not None and self.doc['_class'] == 'Application' and key == 'action'

    def __getitem__(self, key):
        #util.debugLog(self, "__getitem__: key: {}".format(key))
        key = self.__keytransform__(key)
        if self.is_application(key):
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
        if not self.is_application(key):     # dynamically populated each request
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
            if a[0] != '_':
                if "action" in self.tree['app'][a]:
                    del self.tree['app'][a]['action']

    def update(self):
        self.clean_actions()
        root_tree = self.db['root_tree'].find_one()
        self.db['root_tree'].update({"_id": root_tree['_id']}, self.tree)

