from persistent.mapping import PersistentMapping
import datetime
import hashlib
import uuid
import base64
import os.path
import shutil

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


#global handle for the root object, so all views have access
root = None

class RootService:
    def __init__(self):
        self.root = root

    def Application(self, app):
        return self.root['app_root']['app'][app]

    def ApplicationContainer(self):
        return self.root['app_root']['app']

    def BuildContainer(self, app):
        return self.root['app_root']['app'][app]['builds']

    def ActionContainer(self, app):
        return self.root['app_root']['app'][app]['action']

    def UserContainer(self):
        return self.root['app_root']['global']['users']


class DataService:
    def __init__(self):
        self.rs = RootService()

    def Builds(self, app_name):
        return self.rs.BuildContainer(app_name)

    def Applications(self):
        return self.rs.ApplicationContainer()

    def NewAction(self, app_name, action_name, params, callable):
        util.debugLog(self, "NewAction: app_name: {}".format(app_name))
        util.debugLog(self, "NewAction: action_name: {}".format(action_name))
        action = Action(app_name, action_name, params, callable)
        self.rs.ActionContainer(app_name)[action_name] = action

    def NewBuild(self, app_name, build_name, attribs, subsys):
        build = Build(app_name, build_name, attributes=attribs, subsys=subsys)
        build["info"] = BuildDetail(build)
        self.rs.BuildContainer(app_name)[build_name] = build

    def DeleteBuild(self, app_name, build_name):
        self.rs.BuildContainer(app_name).remove_build(build_name)

    def NewApplication(self, app_name):
        app = Application(app_name)
        app['environments'] = EnvironmentContainer(app_name)
        app['builds'] = BuildContainer(app_name)
        app['subsys'] = SubsystemContainer(app_name)
        app['action'] = ActionContainer(app_name)
        self.rs.ApplicationContainer()[app_name] = app

    def DeleteApplication(self, app_name):
        self.rs.ApplicationContainer().pop(app_name, None)

    def GetUsers(self):
        return self.rs.UserContainer()

    def GetUser(self, username):
        return self.rs.UserContainer()[username]

class SupportedFileType:
    TarGz = 'tar.gz'
    TarBz2 = 'tar.bz2'
    Zip = 'zip'
    types = [TarBz2, TarGz, Zip]
    

class BaseModelObject(PersistentMapping):
    def __init__(self):
        PersistentMapping.__init__(self)
        self.created_datetime = datetime.datetime.now()


class Server:
    env_name = None

class Deployment:
    env_name = None

class Environment:
    app_name = None

class EnvironmentContainer(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class Build(BaseModelObject):
    def __init__(self, app_name, build_name, attributes={}, subsys=[]):
        BaseModelObject.__init__(self)
        self.app_name = app_name
        self.build_name = build_name
        self.attributes = attributes
        self.subsys = subsys
        self.stored = False
        self.files = dict()  # { filename: filetype }
        self.master_file = None  # original uploaded file
        self.packages = dict()  # { package_type: {'filename': filename, 'file_type': file_type}}

class BuildDetail(BaseModelObject):
    def __init__(self, buildobj):
        BaseModelObject.__init__(self)
        self.buildobj = buildobj

class BuildContainer(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

    def remove_build(self, buildname):
        dir = daft_config.DaftConfiguration().get_build_dir()
        path = "{root_dir}/{app}/{build}".format(root_dir=dir, app=self.app_name, build=buildname)
        util.debugLog(self, "remove_build: path: {}".format(path))
        if os.path.isdir(path):
            util.debugLog(self, "remove_build: deleting")
            shutil.rmtree(path)
        del self[buildname]

class Subsystem(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class SubsystemContainer(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class Action(BaseModelObject):
    def __init__(self, app_name, action_name, params, callable):
        BaseModelObject.__init__(self)
        self.app_name = app_name
        self.action_name = action_name
        self.params = params
        self.callable = callable

    def execute(self, params, verb):
        return self.callable(DataService()).start(params, verb)

class ActionContainer(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class Application(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class User(BaseModelObject):
    def __init__(self, name, permissions, salt, attributes={}):
        BaseModelObject.__init__(self)
        util.debugLog(self, "user: {}".format(name))
        self.salt = salt
        util.debugLog(self, "got salt: {}".format(self.salt))
        self.name = name
        util.debugLog(self, "hashed pw: {}".format(self.hashed_pw))
        self.permissions = permissions
        self.attributes = attributes

    def hash_pw(self, pw):
        return base64.urlsafe_b64encode(hashlib.sha512(pw + self.salt).hexdigest())

    def validate_password(self, pw):
        return self.hashed_pw == self.hash_pw(pw)

    def change_password(self, new_pw):
        self.hashed_pw = self.hash_pw(new_pw)

class UserContainer(BaseModelObject):
    def __init__(self):
        BaseModelObject.__init__(self)
        self.salt = base64.urlsafe_b64encode((uuid.uuid4().bytes))

class TokenContainer(BaseModelObject):
    def __init__(self):
        BaseModelObject.__init__(self)
        self.usermap = dict()  # for quick token lookup by user

    def __setitem__(self, key, value):
        BaseModelObject.__setitem__(self, key, value)
        if value.username in self.usermap:
            self.usermap[value.username].append(value)
        else:
            self.usermap[value.username] = [value]

    def get_tokens_by_username(self, username):
        return self.usermap[username] if username in self.usermap else []

    def remove_token(self, token):
        username = self[token].username
        for t in self.usermap[username]:
            if t.token == token:
                self.usermap[username].remove(t)
        del self[token]

    def new_token(self, username):
        tokenobj = Token(username)
        self[tokenobj.token] = tokenobj
        return tokenobj.token

class Token(BaseModelObject):
    def __init__(self, username, token=None):
        BaseModelObject.__init__(self)
        self.username = username
        self.token = base64.urlsafe_b64encode(hashlib.sha256(uuid.uuid4().bytes).hexdigest())[:-2] \
            if token is None else token

class ApplicationContainer(BaseModelObject):
    pass

class GlobalContainer(BaseModelObject):
    pass

class RootApplication(BaseModelObject):
    pass

#-------------- New data model ---------------------

#containers are subclasses of GenericTreeDict


class GenericTreeDict(dict):
    def __init__(self, tree, subtree, db, child_class):
        dict.__init__(self)
        self.tree = tree            # current tree structure
        self.subtree = subtree      # child tree structure(s), if None then use the __getitem__ item
        self.db = db
        self.child_class = child_class  # class of child items

    def __getitem__(self, item):
        args = [self.tree, item if self.subtree is None else self.subtree]
        if 'doc' in self.tree[item]:
            doc = self.db.dereference(self.tree[item]['doc'])
            if doc is None:
                raise KeyError
            args += [doc[a] for a in doc]
        return self.child_class(args)

class ApplicationModelObject:
    def __init__(self, app_name):
        self.app_name = app_name

class UserModelObject:
    def __init__(self, tree, subtree, name, permissions, salt, attributes):
        self.tree = tree
        self.subtree = subtree
        self.name = name
        self.permissions = permissions
        self.salt = salt
        self.attributes = attributes

class TokenModelObject:
    def __init__(self, tree, subtree, username, token):
        self.username = username
        self.token = token

class AppContainerTreeDict(GenericTreeDict):
    def __init__(self, app_tree, db):
        GenericTreeDict.__init__(self, app_tree, None, db, ApplicationModelObject)

class UserContainerTreeDict(GenericTreeDict):
    def __init__(self, user_tree, db):
        GenericTreeDict.__init__(self, user_tree, None, db, UserModelObject)

class TokenContainerTreeDict(GenericTreeDict):
    def __init__(self, token_tree, db):
        GenericTreeDict.__init__(self, token_tree, None, db, TokenModelObject)

class GlobalContainerTreeDict(GenericTreeDict):
    def __init__(self, global_tree, db):
        GenericTreeDict.__init__(self, global_tree, ('users', 'tokens'), db,
                                 (UserContainerTreeDict, TokenContainerTreeDict))

    def __getitem__(self, item):
        if item == "users":
            self.child_class = self.child_class[0]
            self.subtree = self.subtree[0]
        elif item == "tokens":
            self.child_class = self.child_class[1]
            self.subtree = self.subtree[1]
        return GenericTreeDict.__getitem__(self, item)

class RootTree(GenericTreeDict):
    def __init__(self, root_tree, db):
        GenericTreeDict.__init__(self, root_tree, ('global', 'app'), db,
                                 (GlobalContainerTreeDict, AppContainerTreeDict))

    def __getitem__(self, item):
        if item == "global":
            self.child_class = self.child_class[0]
            self.subtree = self.subtree[0]
        elif item == "app":
            self.child_class = self.child_class[1]
            self.subtree = self.subtree[1]
        else:
            return
        return GenericTreeDict.__getitem__(self, item)


def appmaker(db):
    return RootTree(db['root_tree'].find_one(), db)
