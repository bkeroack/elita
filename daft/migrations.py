import random
from . import util
from . import models

__author__ = 'bkeroack'



def run_migrations(root):
    # TODO: iterate through class names rather than hard coding in migrations
    util.debugLog(object, "Running object migrations...")
    migrations = [GitflowFix_1000, Security_1001, Token_usermap_1002, User_attributes_1003, User_permissions_1004,
                  Build_keys_and_objects_1005, Build_attributes_1006]
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