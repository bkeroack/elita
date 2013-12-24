import util
from pkg_resources import iter_entry_points
import daft
import models
import celeryinit

__author__ = 'bkeroack'

@celeryinit.celery_app.task(bind=True, name="daft_task_run_job")
def run_job(self, callable, args):
    ''' Generate new dataservice, run callable, store results
    '''
    job_id = self.request.id
    db, root, client = daft.MongoClientData()
    datasvc = models.DataService(db, root)
    results = callable(datasvc, args)
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
        job = self.datasvc.NewJob(action_name)
        run_job.apply_async((action, {'params': params, 'verb': verb}), task_id=job.id)
        return {"action": action_name, "job_id": job.id, "status": "async/running"}


class HookStub:
    def __init__(self):
        pass

    def go(self):
        return True

DefaultHookMap = {
    'BUILD_UPLOAD_SUCCESS': HookStub
}

class RegisterHooks:
    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.hookmap = dict()

    def register(self):
        for obj in iter_entry_points(group="daft.modules", name="register_hooks"):
            hooks = obj()  # returns: { app: { "HOOK_NAME": <callable> } }
            for app in hooks:
                for a in hooks[app]:
                    self.hookmap[app] = DefaultHookMap
                    self.hookmap[app][a] = hooks[app][a]
            util.debugLog(self, "HookMap: {}".format(self.hookmap))

    def run_hook(self, app, name, args):
        job = self.datasvc.NewJob("hook: {} (app: {})".format(name, app))
        util.debugLog(self, "run_hook: job_id: {}; app: {}; name: {}; args: {}".format(job.id, app, name, args))
        run_job.apply_async((self.hookmap[app][name], args), task_id=job.id)



class RegisterActions:
    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.actionmap = dict()

    def register(self):
        util.debugLog(self, "register")
        for obj in iter_entry_points(group="daft.modules", name="register_actions"):
            actions = obj()
            util.debugLog(self, "actions: {}".format(actions))
            for app in actions:
                if app not in self.actionmap:
                    self.actionmap[app] = dict()
                for a in actions[app]:
                    action_name = a.__name__
                    params = a.params()
                    self.actionmap[app][action_name] = {"callable": a, "params": params}
                    util.debugLog(self, "NewAction: app: {}; action_name: {}; params: {}".format(app, action_name, params))
                    self.datasvc.NewAction(app, action_name, params)
