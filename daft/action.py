import util
from pkg_resources import iter_entry_points
import daft_config
import models
import celeryinit
import pymongo
import daft

__author__ = 'bkeroack'

@celeryinit.celery.task(bind=True, name="daft_task_run_job")
def run_job(self, mdb_info, callable, args):
    ''' Generate new dataservice, run callable, store results
    '''
    job_id = self.request.id
    client = pymongo.MongoClient(mdb_info['host'], mdb_info['port'])
    db = client[mdb_info['db']]
    tree = db['root_tree'].find_one()
    updater = models.RootTreeUpdater(tree, db)
    root = models.RootTree(db, updater, tree, None)
    datasvc = models.DataService(db, root)
    results = callable(datasvc, **args)
    datasvc.SaveJobResults(job_id, results)
    client.close()


class ActionService:
    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.hooks = RegisterHooks(self.datasvc)
        self.hooks.register()
        self.actions = RegisterActions(self.datasvc)
        self.actions.register()

    def async(self, app, action_name, params, verb):
        action = self.actions.actionmap[app][action_name]['callable']
        util.debugLog(self, "action: {}, params: {}, verb: {}".format(action, params, verb))
        job = self.datasvc.NewJob(action_name)
        job_id = str(job.id)
        run_job.apply_async((daft_config.cfg.get_mongo_server(), action, {'params': params, 'verb': verb}), task_id=job_id)
        return {"action": action_name, "job_id": job_id, "status": "async/running"}


DefaultHookMap = {
    'BUILD_UPLOAD_SUCCESS': None
}

class RegisterHooks:
    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.hookmap = dict()

    def register(self):
        for obj in iter_entry_points(group="daft.modules", name="register_hooks"):
            hooks = (obj.load())()  # returns: { app: { "HOOK_NAME": <callable> } }
            for app in hooks:
                for a in hooks[app]:
                    self.hookmap[app] = DefaultHookMap
                    self.hookmap[app][a] = hooks[app][a]
            util.debugLog(self, "HookMap: {}".format(self.hookmap))

    def run_hook(self, app, name, args):
        hook = self.hookmap[app][name]
        if hook is None:
            return "none"
        job = self.datasvc.NewJob("hook: {} (app: {})".format(name, app))
        job_id = str(job.id)
        util.debugLog(self, "run_hook: job_id: {}; app: {}; name: {}; args: {}".format(job.id, app, name, args))
        run_job.apply_async((daft_config.cfg.get_mongo_server(), hook, args), task_id=job_id)
        return {
            "hook": {
                name: {
                    "status": "async/running",
                    "job_id": job_id
                }
            }
        }



class RegisterActions:
    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.actionmap = dict()

    def register(self):
        util.debugLog(self, "register")
        for obj in iter_entry_points(group="daft.modules", name="register_actions"):
            util.debugLog(self, "register: found obj: {}".format(obj))
            actions = (obj.load())()
            util.debugLog(self, "actions: {}".format(actions))
            for app in actions:
                if app not in self.actionmap:
                    self.actionmap[app] = dict()
                for a in actions[app]:
                    action_name = a['callable'].__name__
                    self.actionmap[app][action_name] = a
                    util.debugLog(self, "NewAction: app: {}; action_name: {}; params: {}".format(app, action_name, a['params']))
                    self.datasvc.NewAction(app, action_name, a['params'])
