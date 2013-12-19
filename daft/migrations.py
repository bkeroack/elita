import random
import pymongo
import bson
import datetime

from . import util
from . import models
import daft_config

__author__ = 'bkeroack'



def run_migrations(root):
    # TODO: iterate through class names rather than hard coding in migrations
    util.debugLog(object, "Running object migrations...")
    migrations = [GitflowFix_1000, Security_1001, Token_usermap_1002, User_attributes_1003, User_permissions_1004,
                  Build_keys_and_objects_1005, Build_attributes_1006, Mongodb_1007]
    for m in migrations:
        try:
            mo = m(root)
        except AssertionError:
            util.debugLog(object, "not running: {}".format(m.__name__))
            continue
        root = mo.run()
    return root


# Migration classes are expected to throw AssertionError in init if they aren't applicable or have already run

class GitflowFix_1000:
    ''' Fix for gitflow problem with 'feature/xxx' branch naming convention breaking routes
    '''
    def __init__(self, root):
        assert False  # don't need to run this constantly anymore
        assert 'app_root' in root
        assert 'app' in root['app_root']
        assert 'scorebig' in root['app_root']['app']
        assert 'builds' in root['app_root']['app']['scorebig']
        self.root = root

    def run(self):
        util.debugLog(self, "running")
        for b in self.root['app_root']['app']['scorebig']['builds']:
            if '/' in b:
                util.debugLog(self, "migrating {}".format(b))
                bobj = self.root['app_root']['app']['scorebig']['builds'][b]
                del self.root['app_root']['app']['scorebig']['builds'][b]
                new_b = str(b).replace('/', '-')
                i = 0
                while new_b in self.root['app_root']['app']['scorebig']['builds']:
                    new_b += '_' if i == 0 else ''
                    new_b += "{}".format(random.choice(range(0, 10)))
                    i += 1
                bobj.build_name = new_b
                self.root['app_root']['app']['scorebig']['builds'][new_b] = bobj
        return self.root


class Security_1001:
    ''' Addition of Users and permissions, initial version
    '''
    def __init__(self, root):
        assert 'app_root' in root
        assert 'global' not in root['app_root']
        #assert 'users' not in root['app_root']['global']
        self.root = root

    def run(self):
        util.debugLog(self, "running")
        if 'global' not in self.root['app_root']:
            self.root['app_root']['global'] = models.GlobalContainer()
        #del self.root['app_root']['global']['users']
        if 'users' not in self.root['app_root']['global']:
            uc = models.UserContainer()
            self.root['app_root']['global']['users'] = uc
        if 'admin' not in self.root['app_root']['global']['users']:
            uc = self.root['app_root']['global']['users']
            self.root['app_root']['global']['users']['admin'] = models.User('admin', "daft", {"_global": "read;write"}, uc.salt)
        #del self.root['app_root']['global']['tokens']
        if 'tokens' not in self.root['app_root']['global']:
            self.root['app_root']['global']['tokens'] = models.TokenContainer()
            tk = models.Token('admin')
            self.root['app_root']['global']['tokens'][tk.token] = tk
        return self.root

class Token_usermap_1002:
    '''Addition of usermap to TokenContainer
    '''
    def __init__(self, root):
        assert not hasattr(root['app_root']['global']['tokens'], "usermap")
        #assert True
        self.root = root

    def run(self):
        util.debugLog(self, "running")
        self.root['app_root']['global']['tokens'].usermap = dict()
        for i, t in enumerate(self.root['app_root']['global']['tokens']):
            to = self.root['app_root']['global']['tokens'][t]
            if to.username not in self.root['app_root']['global']['tokens'].usermap:
                self.root['app_root']['global']['tokens'].usermap[to.username] = list()
            else:
                self.root['app_root']['global']['tokens'].usermap[to.username].append(to)
        util.debugLog(self, "{} tokens added to usermap".format(i))
        return self.root


class User_attributes_1003:
    '''Addition of attributes field to User
    '''
    def __init__(self, root):
        for u in root['app_root']['global']['users']:
            uobj = root['app_root']['global']['users'][u]
            assert not hasattr(uobj, "attributes")
        self.root = root

    def run(self):
        util.debugLog(self, "running")
        for u in self.root['app_root']['global']['users']:
            uobj = self.root['app_root']['global']['users'][u]
            if not hasattr(uobj, "attributes"):
                util.debugLog(self, "...adding attributes to user '{}'".format(u))
                self.root['app_root']['global']['users'][u].attributes = dict()
        return self.root


class User_permissions_1004:
    '''Top-level apps and actions containers in permissions object
    '''
    def __init__(self, root):
        run = False
        for u in root['app_root']['global']['users']:
            uobj = root['app_root']['global']['users'][u]
            for p in uobj.permissions:
                if p not in ('actions', 'apps'):
                    util.debugLog(self, "...{} is not apps or actions".format(p))
                    run = True
        assert run
        self.root = root

    def run(self):
        util.debugLog(self, "running")
        for u in self.root['app_root']['global']['users']:
            uobj = self.root['app_root']['global']['users'][u]
            dkeys = list()
            app_perms = dict()
            for k in uobj.permissions:
                if k not in ('actions', 'apps'):
                    util.debugLog(self, "...user: '{}': migrating perm block '{}'".format(u, k))
                    dkeys.append(k)
                    app_perms[k] = uobj.permissions[k]
            if len(app_perms) > 0:
                util.debugLog(self, "...setting app_perms")
                uobj.permissions['apps'] = app_perms
            util.debugLog(self, "...dkeys: {}".format(dkeys))
            for k in dkeys:
                del uobj.permissions[k]
            self.root['app_root']['global']['users'][u].permissions = uobj.permissions
        return self.root

class Build_keys_and_objects_1005:
    '''Make sure BuildContainer key matches resulting object.build_name attribute
    '''
    def __init__(self, root):
        assert False
        self.root = root

    def run(self):
        util.debugLog(self, "running")
        i = 0
        for app in self.root['app_root']['app']:
            for b in self.root['app_root']['app'][app]['builds']:
                bobj = self.root['app_root']['app'][app]['builds'][b]
                if b != bobj.build_name:
                    util.debugLog(self, "{} does not match {}".format(b, bobj.build_name))
                    #assume the key is correct
                    bobj.build_name = b
                    self.root['app_root']['app'][app]['builds'][b] = bobj
                    i += 1
        util.debugLog(self, "{} total objects fixed".format(i))
        return self.root

class Build_attributes_1006:
    '''Add attributes field to Build objects
    '''
    def __init__(self, root):
        assert False
        self.root = root

    def run(self):
        util.debugLog(self, "running")
        i = 0
        for app in self.root['app_root']['app']:
            for b in self.root['app_root']['app'][app]['builds']:
                bobj = self.root['app_root']['app'][app]['builds'][b]
                if not hasattr(bobj, "attributes"):
                    bobj.attributes = dict()
                    self.root['app_root']['app'][app]['builds'][b] = bobj
                    i += 1
        util.debugLog(self, "{} builds processed".format(i))


class Mongodb_1007:
    '''Migrate all data to mongo
    '''
    def __init__(self, root):
        assert True
        self.root = root
        mongo_info = daft_config.cfg.get_mongo_server()
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
        util.debugLog(self, "running")
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
        util.debugLog(self, "...users")
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
        util.debugLog(self, "...{} users".format(i))

    def tokens(self):
        util.debugLog(self, "...tokens")
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
        util.debugLog(self, "...{} tokens".format(i))

    def applications(self):
        util.debugLog(self, "...applications")
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
        util.debugLog(self, "...{} applications".format(i))

    def builds(self):
        util.debugLog(self, "...builds")
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
        util.debugLog(self, "...{} builds".format(i))



