import random
from . import util
from . import models

__author__ = 'bkeroack'



def run_migrations(root):
    # TODO: iterate through class names rather than hard coding in migrations
    util.debugLog(object, "Running object migrations...")
    migrations = [GitflowFix_1000, Security_1001, Token_usermap_1002]
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
        assert 'users' not in root['app_root']['global']
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
        #assert not hasattr(root['app_root']['global']['tokens'], "usermap")
        assert True
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

