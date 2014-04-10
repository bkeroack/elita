import util
import models
import celeryinit
import pymongo
import sys
import traceback

__author__ = 'bkeroack'

def regen_datasvc(settings, job_id):
    client = pymongo.MongoClient(settings['daft.mongo.host'], int(settings['daft.mongo.port']))
    db = client[settings['daft.mongo.db']]
    tree = db['root_tree'].find_one()
    updater = models.RootTreeUpdater(tree, db)
    root = models.RootTree(db, updater, tree, None)
    return client, models.DataService(settings, db, root, job_id=job_id)

@celeryinit.celery.task(bind=True, name="daft_task_run_job")
def run_job(self, settings, callable, args):
    ''' Generate new dataservice, run callable, store results
    '''
    job_id = self.request.id
    client, datasvc = regen_datasvc(settings, job_id)
    try:
        results = callable(datasvc, **args)
    except:
        exc_type, exc_obj, tb = sys.exc_info()
        f_exc = traceback.format_exception(exc_type, exc_obj, tb)
        results = {
            "error": "unhandled exception during callable!",
            "exception": f_exc
        }
        util.debugLog(run_job, "EXCEPTION: {}".format(f_exc))
    datasvc.jobsvc.SaveJobResults(results)
    client.close()

#generic interface to run code async (not explicit named actions/hooks)
def run_async(datasvc, name, callable, args):
    util.debugLog("run_async", "create new async task: {}; args: {}".format(callable, args))
    job = datasvc.jobsvc.NewJob("run_async: {}".format(name))
    job_id = str(job.job_id)
    run_job.apply_async((datasvc.settings, callable, args), task_id=job_id)
    return job_id

class ActionService:
    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.hooks = RegisterHooks(self.datasvc)
        self.hooks.register()
        self.actions = RegisterActions(self.datasvc)
        self.actions.register()

    def get_action_details(self, app, action_name):
        return self.actions.actionmap[app][action_name] if app in self.actions.actionmap and action_name in self\
            .actions.actionmap[app] else None

    def async(self, app, action_name, params):
        action = self.actions.actionmap[app][action_name]['callable']
        util.debugLog(self, "action: {}, params: {}".format(action, params))
        job = self.datasvc.jobsvc.NewJob(action_name)
        job_id = str(job.job_id)
        run_job.apply_async((self.datasvc.settings, action, {'params': params}), task_id=job_id)
        return {"action": action_name, "job_id": job_id, "status": "async/running"}


DefaultHookMap = {
    'BUILD_UPLOAD_SUCCESS': None,
    'GITDEPLOY_INIT_PRE': None,
    'GITDEPLOY_INIT_POST': None,
    'GITDEPLOY_DEINIT_PRE': None,
    'GITDEPLOY_DEINIT_POST': None,
    'GITDEPLOY_COMMIT_DIFF': None
}

class RegisterHooks:
    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.hookmap = dict()

    def register(self):
        #first load all defaults
        for app in self.datasvc.appsvc.GetApplications():
            self.hookmap[app] = DefaultHookMap
        from pkg_resources import iter_entry_points
        for obj in iter_entry_points(group="daft.modules", name="register_hooks"):
            hooks = (obj.load())()  # returns: { app: { "HOOK_NAME": <callable> } }
            for app in hooks:
                for a in hooks[app]:
                    self.hookmap[app][a] = hooks[app][a]
            util.debugLog(self, "HookMap: {}".format(self.hookmap))

    def run_hook(self, app, name, args):
        hook = self.hookmap[app][name]
        if hook is None:
            return "none"
        args['datasvc'] = self.datasvc
        return hook(**args)


class RegisterActions:
    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.actionmap = dict()

    def register(self):
        util.debugLog(self, "register")

        from pkg_resources import iter_entry_points
        apps = self.datasvc.appsvc.GetApplications()

        for obj in iter_entry_points(group="daft.modules", name="register_actions"):
            util.debugLog(self, "register: found obj: {}".format(obj))
            actions = (obj.load())()
            util.debugLog(self, "actions: {}".format(actions))
            for app in actions:
                if app not in apps:
                    util.debugLog(self, "WARNING: application not found: {}".format(app))
                else:
                    if app not in self.actionmap:
                        self.actionmap[app] = dict()
                    for a in actions[app]:
                        action_name = a['callable'].__name__
                        self.actionmap[app][action_name] = a
                        util.debugLog(self, "NewAction: app: {}; action_name: {}; params: {}".format(app, action_name, a['params']))
                        params = a['params'].keys()
                        self.datasvc.jobsvc.NewAction(app, action_name, params)
