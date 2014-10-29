__author__ = 'bkeroack'

import logging
import bson
import collections

import elita.util
import models

DEFAULT_ADMIN_USERNAME = 'admin'
DEFAULT_ADMIN_PASSWORD = 'elita'
DEFAULT_ADMIN_PERMISSIONS = {
    'apps': {
        '*': 'read/write',
        '_global': 'read/write'
    },
    'actions': {
        '*': {
            '*': 'execute'
        }
    },
    'servers': ['*']
}

class DataValidator:
    '''
    Responsible for:
        - Creating proper data model/root_tree on first run
        - Validating that data isn't broken/inconsistent
        - Running migrations between versions
    '''
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, settings, root, db):
        '''
        @type settings: pyramid.registry.Registry
        @type root: dict
        @type db: pymongo.database.Database
        '''
        # root is optional if this is the first time elita runs
        assert settings and db
        self.settings = settings
        self.root = root
        self.db = db

    def run(self):
        # order is very significant
        logging.debug("running")
        self.check_root()
        self.check_toplevel()
        self.check_global()
        self.check_root_references()
        self.check_users()
        self.check_user_permissions()
        self.check_doc_consistency()
        self.check_containers()
        self.check_apps()
        self.check_jobs()
        self.check_deployments()
        self.check_servers()
        self.check_gitdeploys()
        self.check_gitrepos()
        self.check_groups()
        self.SaveRoot()

    def SaveRoot(self):
        logging.debug('saving root_tree')
        self.db['root_tree'].save(self.root)

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
            'servers',
            'groups',
            'packagemaps'
        ]
        for c in collects:
            rm_docs = list()
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
                    if self.root['app'][d['app_name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked application document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'builds':
                    if d['build_name'] not in self.root['app'][d['app_name']]['builds']:
                        logging.warning("orphan build object: '{}/{}', adding to root tree".format(d['app_name'], d['build_name']))
                        self.root['app'][d['app_name']]['builds'][d['build_name']] = {'_doc': bson.DBRef('builds', d['_id'])}
                    if self.root['app'][d['app_name']]['builds'][d['build_name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked build document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'gitproviders':
                    if d['name'] not in self.root['global']['gitproviders']:
                        logging.warning("orphan gitprovider object: '{}', adding to root tree".format(d['name']))
                        self.root['global']['gitproviders'][d['name']] = {'_doc': bson.DBRef('gitproviders', d['_id'])}
                    if self.root['global']['gitproviders'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked gitprovider document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'gitrepos':
                    if d['name'] not in self.root['app'][d['application']]['gitrepos']:
                        logging.warning("orphan gitrepo object: '{}/{}', adding to root tree".format(d['application'], d['name']))
                        self.root['app'][d['application']]['gitrepos'][d['name']] = {'_doc': bson.DBRef('gitrepos', d['_id'])}
                    if self.root['app'][d['application']]['gitrepos'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked gitrepo document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'gitdeploys':
                    if d['name'] not in self.root['app'][d['application']]['gitdeploys']:
                        logging.warning("orphan gitdeploy object: '{}/{}', adding to root tree".format(d['application'], d['name']))
                        self.root['app'][d['application']]['gitdeploys'][d['name']] = {'_doc': bson.DBRef('gitdeploys', d['_id'])}
                    if self.root['app'][d['application']]['gitdeploys'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked gitdeploy document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'jobs':
                    if d['job_id'] not in self.root['job']:
                        logging.warning("orphan job object: '{}', adding to root tree".format(d['job_id']))
                        self.root['job'][d['job_id']] = {'_doc': bson.DBRef('jobs', d['_id'])}
                    #we don't really care about unlinked jobs
                if c == 'tokens':
                    if d['token'] not in self.root['global']['tokens']:
                        logging.warning("orphan token object: '{}', adding to root tree".format(d['token']))
                        self.root['global']['tokens'][d['token']] = {'_doc': bson.DBRef('tokens', d['_id'])}
                    if self.root['global']['tokens'][d['token']]['_doc'].id != d['_id']:
                        logging.warning("unlinked token document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'users':
                    if d['username'] not in self.root['global']['users']:
                        logging.warning("orphan user object: '{}', adding to root tree".format(d['username']))
                        self.root['global']['users'][d['username']] = {'_doc': bson.DBRef('users', d['_id'])}
                    if self.root['global']['users'][d['username']]['_doc'].id != d['_id']:
                        logging.warning("unlinked user document found ({}), deleting".format(d['username']))
                        rm_docs.append(d['_id'])
                if c == 'servers':
                    if d['name'] not in self.root['server']:
                        logging.warning("orphan server object: '{}', adding to root tree".format(d['name']))
                        self.root['server'][d['name']] = {'_doc': bson.DBRef('servers', d['_id'])}
                    if self.root['server'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked server document found, deleting")
                        rm_docs.append(d['_id'])
                if c == 'groups':
                    if d['name'] not in self.root['app'][d['application']]['groups']:
                        logging.warning("orphan group object: '{}', adding to root tree".format(d['name']))
                        self.root['app'][d['application']]['groups'][d['name']] = {'_doc': bson.DBRef('groups', d['_id'])}
                    if self.root['app'][d['application']]['groups'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked group document found ({}), deleting".format(d['name']))
                        rm_docs.append(d['_id'])
                if c == 'packagemaps':
                    if d['name'] not in self.root['app'][d['application']]['packagemaps']:
                        logging.warning("orphan packagemap object: '{}', adding to root tree".format(d['name']))
                        self.root['app'][d['application']]['packagemaps'][d['name']] = {'_doc': bson.DBRef('packagemaps', d['_id'])}
                    if self.root['app'][d['application']]['packagemaps'][d['name']]['_doc'].id != d['_id']:
                        logging.warning("unlinked packagemap document found ({}), deleting".format(d['name']))
                        rm_docs.append(d['_id'])
            for id in rm_docs:
                self.db[c].remove({'_id': id})

    @staticmethod
    def check_root_refs(db, obj):
        '''
        Recurse into obj, find DBRefs, check if they are valid
        '''
        for k in obj:
            if k == '_doc':
                if not db.dereference(obj[k]):
                    logging.warning("Invalid dbref found! {}".format(obj[k].collection))
            elif k[0] != '_' and not isinstance(obj[k], bson.ObjectId):
                DataValidator.check_root_refs(db, obj[k])

    def check_root_references(self):
        '''
        Check that every DBRef in the root tree points to a valid document
        '''
        DataValidator.check_root_refs(self.db, self.root)

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
        if DEFAULT_ADMIN_USERNAME not in self.root['global']['users']:
            logging.warning("admin user not found")
            users = [u for u in self.db['users'].find()]
            if DEFAULT_ADMIN_USERNAME in [u['username'] for u in users]:
                admin = self.db['users'].find_one({'username': DEFAULT_ADMIN_USERNAME})
                assert admin
                self.root['global']['users'][DEFAULT_ADMIN_USERNAME] = {
                    '_doc': bson.DBRef('users', admin['_id'])
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
        users = [u for u in self.db['users'].find()]
        for u in users:
            if 'username' not in u:
                logging.warning("user found without username property; fixing {}".format(u['_id']))
                if 'name' in u:
                    u['username'] = u['name']
                    self.db['users'].save(u)
                else:
                    logging.warning("...couldn't fix user because name field not found!")
        if DEFAULT_ADMIN_USERNAME not in [u['username'] for u in users]:
            logging.warning("admin user document not found; creating")
            userobj = models.User({
                'username': DEFAULT_ADMIN_USERNAME,
                'permissions': DEFAULT_ADMIN_PERMISSIONS,
                'password': DEFAULT_ADMIN_PASSWORD
            })
            doc = userobj.get_doc()
            doc['_class'] = 'User'
            uid = self.db['users'].insert(doc)
            pid = self.db['userpermissions'].insert({
                "_class": "UserPermissions",
                "username": DEFAULT_ADMIN_USERNAME,
                "applications": list(),
                "actions": dict(),
                "servers": list()
            })
            self.root['global']['users'][DEFAULT_ADMIN_USERNAME] = {
                '_doc': bson.DBRef('users', uid),
                'permissions': {
                    '_doc': bson.DBRef('userpermissions', pid)
                }
            }

    def check_user_permissions(self):
        for u in self.db['users'].find():
            if 'permissions' not in u:
                logging.warning("permissions object not found for user {}; fixing with empty obj"
                              .format(u['username']))
                u['permissions'] = {
                    'apps': {},
                    'actions': {},
                    'servers': []
                }
            for o in ('apps', 'actions', 'servers'):
                if o not in u['permissions']:
                    logging.warning("{} not found in permissions object for user {}; fixing with empty "
                                        "obj".format(o, u['username']))
                    u['permissions'][o] = list() if o == 'servers' else dict()
            if not isinstance(u['permissions']['servers'], list):
                logging.warning("servers key under permissions object for user {} is not a list; fixing"
                              .format(u['username']))
                u['permissions']['servers'] = list(u['permissions']['servers'])
            for o in ('apps', 'actions'):
                if not isinstance(u['permissions'][o], dict):
                    logging.warning("{} key under permissions object for user {} is not a dict; invalid "
                                        "so replacing with empty dict".format(o, u['username']))
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
            },
            'packagemaps': {
                'class': "PackageMapContainer"
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
            update = False
            if 'environment' not in d:
                logging.warning("environment field not found for server {}; fixing".format(d['_id']))
                d['environment'] = ""
                update = True
            if 'status' not in d:
                logging.warning("status field not found for server {}; fixing".format(d['_id']))
                d['status'] = "ok"
                update = True
            if update:
                update_list.append(d)
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
            if 'username' not in d:
                logging.warning("found deployment without username: {}; fixing with empty string".format(d['_id']))
                d['username'] = ""
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
            if 'server' in d:
                logging.warning("gitdeploy found with obsolete server field {}; removing".format(d['_id']))
                del d['server']
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
        if not self.root:
            logging.warning("no root_tree found!")
        self.root = dict() if not self.root else self.root
        if '_class' in self.root:
            logging.warning("'_class' found in base of root; deleting")
            del self.root['_class']
        if '_doc' not in self.root:
            logging.warning("'_doc' not found in base of root")
            self.root['_doc'] = self.NewContainer('Root', 'Root', '')
        rt_list = [d for d in self.db['root_tree'].find()]
        if len(rt_list) > 1:
            logging.warning("duplicate root_tree docs found! Removing all but the first")
            for d in rt_list[1:]:
                self.db['root_tree'].remove({'_id': d['_id']})


