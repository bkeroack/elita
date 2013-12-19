from ZODB.FileStorage import FileStorage
from ZODB.DB import DB
from persistent.mapping import PersistentMapping

#not really necessary but used by old classes
import datetime
import os
import shutil
import base64
import hashlib
import uuid
#end superfluous imports

import pymongo
import bson
import logging

import pprint

import daft.daft_config as daft_config
import daft.util as util


logging.basicConfig(level=logging.DEBUG)

__author__ = 'bkeroack'

#old data model classes, so ZODB can load them
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
    def __init__(self, name, pw, permissions, salt, attributes={}):
        BaseModelObject.__init__(self)
        util.debugLog(self, "user: {}, pw: {}".format(name, pw))
        self.salt = salt
        util.debugLog(self, "got salt: {}".format(self.salt))
        self.name = name
        self.hashed_pw = self.hash_pw(pw)
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
    def __init__(self, username):
        BaseModelObject.__init__(self)
        self.username = username
        self.token = base64.urlsafe_b64encode(hashlib.sha256(uuid.uuid4().bytes).hexdigest())[:-2]  # strip '=='

class ApplicationContainer(BaseModelObject):
    pass

class GlobalContainer(BaseModelObject):
    pass

class RootApplication(BaseModelObject):
    pass




#### end old classes



class ZodbStore:
    def __init__(self):
        self.storage = FileStorage('Data.fs')
        self.db = DB(self.storage)
        self.con = self.db.open()
        self.root = self.con.root()
        pp = pprint.PrettyPrinter(indent=4)
        logging.debug("ZodbStore: root: {}".format(pp.pformat(self.root)))

    def close(self):
        import transaction
        transaction.commit()
        self.db.close()


class MongoMigrate:
    def __init__(self, root):
        self.root = root
        cfg = daft_config.DaftConfiguration()
        mongo_info = cfg.get_mongo_server()
        self.client = pymongo.MongoClient(mongo_info['host'], mongo_info['port'])
        dbname = mongo_info['db']
        self.client.write_concern = {'w': 1}
        if dbname in self.client.database_names():
            self.client.drop_database(dbname)
        self.db = self.client[dbname]
        self.root_tree = dict()  # tree w/ dbrefs for mongo insertion

    def setup_root_tree(self):
        self.root_tree['global'] = dict()
        self.root_tree['global']['_doc'] = self.save_container(class_name="GlobalContainer", parent="", name="global")
        self.root_tree['app'] = dict()
        self.root_tree['app']['_doc'] = self.save_container(class_name="AppContainer", parent="", name="app")
        self.root_tree['global']['users'] = dict()
        self.root_tree['global']['tokens'] = dict()

    def run(self):
        logging.debug("running")
        self.setup_root_tree()
        self.users()
        self.tokens()
        self.applications()
        self.builds()
        self.save_root_tree()

    def save_root_tree(self):
        self.drop_if_exists("root_tree")
        root_tree = self.db['root_tree']
        root_tree.insert(self.root_tree)

    def drop_if_exists(self, cname):
        if cname in self.db.collection_names():
            self.db.drop_collection(cname)

    def save_container(self, class_name, parent, name):
        containers = self.db['containers']
        cid = containers.insert({"_class": class_name, "name": name, "parent": parent})
        return bson.DBRef("containers", cid)

    def users(self):
        logging.debug("...users")
        self.drop_if_exists("users")
        users = self.db['users']
        for i, u in enumerate(self.root['app_root']['global']['users']):
            uobj = self.root['app_root']['global']['users'][u]
            id = users.insert({
                "_class": "User",
                "name": uobj.name,
                "salt": uobj.salt,
                "hashed_pw": uobj.hashed_pw,
                "permissions": uobj.permissions,
                "attributes": uobj.attributes
            })
            self.root_tree['global']['users'][uobj.name] = {"_doc": bson.DBRef("users", id)}
        self.root_tree['global']['users']["_doc"] = self.save_container(class_name="UserContainer",
                                                                       parent="global", name="users")
        logging.debug("...{} users".format(i))

    def tokens(self):
        logging.debug("...tokens")
        self.drop_if_exists("tokens")
        tokens = self.db['tokens']
        for i, t in enumerate(self.root['app_root']['global']['tokens']):
            tobj = self.root['app_root']['global']['tokens'][t]
            id = tokens.insert({
                "_class": "Token",
                "username": tobj.username,
                "token": tobj.token
            })
            self.root_tree['global']['tokens'][tobj.token] = {"_doc": bson.DBRef("tokens", id)}
        self.root_tree['global']['tokens']["_doc"] = self.save_container(class_name="TokenContainer",
                                                                        parent="global", name="tokens")
        logging.debug("...{} tokens".format(i))

    def applications(self):
        logging.debug("...applications")
        self.drop_if_exists("applications")
        applications = self.db['applications']
        for i, a in enumerate(self.root['app_root']['app']):
            aobj = self.root['app_root']['app'][a]
            id = applications.insert({
                "_class": "Application",
                "app_name": aobj.app_name
            })
            self.root_tree['app'][aobj.app_name] = {"_doc": bson.DBRef("applications", id)}
            self.root_tree['app'][aobj.app_name]['action'] = dict()
            self.root_tree['app'][aobj.app_name]['action']['_doc'] = self.save_container(class_name="ActionContainer",
                                                                                         parent=aobj.app_name,
                                                                                         name="action")
        self.root_tree['app']["_doc"] = self.save_container(class_name="AppContainer", parent="", name="app")
        logging.debug("...{} applications".format(i))

    def builds(self):
        logging.debug("...builds")
        self.drop_if_exists("builds")
        builds = self.db['builds']
        i = 0
        for a in self.root['app_root']['app']:
            self.root_tree['app'][a]['builds'] = dict()
            for b in self.root['app_root']['app'][a]['builds']:
                bobj = self.root['app_root']['app'][a]['builds'][b]
                flist = list()
                for f in bobj.files:
                    flist.append({
                        "path": f,
                        "file_type": bobj.files[f]
                    })
                id = builds.insert({
                    "_class": "Build",
                    "app_name": bobj.app_name,
                    "build_name": bobj.build_name,
                    "attributes": bobj.attributes,
                    "stored": bobj.stored,
                    "files": flist,
                    "master_file": bobj.master_file,
                    "packages": bobj.packages
                })
                self.root_tree['app'][a]['builds'][bobj.build_name] = {"_doc": bson.DBRef("builds", id)}
                i += 1
            self.root_tree['app'][a]['builds']["_doc"] = self.save_container(class_name="BuildContainer",
                                                                            parent=a, name="builds")
        logging.debug("...{} builds".format(i))


if __name__ == '__main__':
    logging.debug("Running Mongo migration")
    zs = ZodbStore()
    mm = MongoMigrate(zs.root)
    mm.run()
    zs.close()

