import logging
import random

__author__ = 'bkeroack'

def debugLog(self, msg):
    logging.info("{}: {}".format(self.__class__.__name__, msg))

def run_migrations(root):
    # TODO: iterate through class names rather than hard coding in migrations
    logging.info("Running object migrations...")
    return GitflowFix_1000(root).run()


class GitflowFix_1000:
    ''' Fix for gitflow problem with 'feature/xxx' branch naming convention breaking routes
    '''
    def __init__(self, root):
        assert 'app_root' in root
        assert 'app' in root['app_root']
        assert 'scorebig' in root['app_root']['app']
        assert 'builds' in root['app_root']['app']['scorebig']
        self.root = root

    def run(self):
        debugLog(self, "running")
        for b in self.root['app_root']['app']['scorebig']['builds']:
            if '/' in b:
                debugLog(self, "migrating {}".format(b))
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
