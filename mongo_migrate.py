from ZODB.FileStorage import FileStorage
from ZODB.DB import DB


import pymongo
import bson
import sys

import daft.daft_config as daft_config

import logging

__author__ = 'bkeroack'

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
lh = logging.StreamHandler(sys.stdout)
lh.setLevel(logging.DEBUG)
logger.addHandler(lh)

class ZodbStore:
    def __init__(self):
        self.storage = FileStorage('Data.fs')
        self.db = DB(self.storage)
        self.con = self.db.open()
        self.root = self.con.root()

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
        logger.debug("running")
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
        logger.debug("...users")
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
        logger.debug("...{} users".format(i))

    def tokens(self):
        logger.debug("...tokens")
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
        logger.debug("...{} tokens".format(i))

    def applications(self):
        logger.debug("...applications")
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
        logger.debug("...{} applications".format(i))

    def builds(self):
        logger.debug("...builds")
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
        logger.debug("...{} builds".format(i))


if __name__ == '__main__':
    logger.debug("MongoMigrate: beginning data migration")
    zs = ZodbStore()
    mm = MongoMigrate(zs.root)
    mm.run()
    zs.close()

