import pymongo
import sys
import traceback
import logging

import elita.util
import elita.models
import elita.celeryinit

__author__ = 'bkeroack'

def regen_datasvc(settings, job_id):
    client = pymongo.MongoClient(settings['elita.mongo.host'], int(settings['elita.mongo.port']))
    db = client[settings['elita.mongo.db']]
    tree = db['root_tree'].find_one()
    updater = elita.models.RootTreeUpdater(tree, db)
    root = elita.models.RootTree(db, updater, tree, None)
    return client, elita.models.DataService(settings, db, root, job_id=job_id)

@elita.celeryinit.celery.task(bind=True, name="elita_task_run_job")
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
        logging.debug("EXCEPTION: {}".format(f_exc))
    datasvc.jobsvc.SaveJobResults(results if results else {"status": "job returned no data"})
    client.close()

#generic interface to run code async (not explicit named actions/hooks)
def run_async(datasvc, name, job_type, data, callable, args):
    logging.debug("run_async: create new async task: {}; args: {}".format(callable, args))
    job = datasvc.jobsvc.NewJob(name, job_type, data)
    job_id = str(job.job_id)
    run_job.apply_async((datasvc.settings, callable, args), task_id=job_id)
    return job_id

class ActionService:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, datasvc):
        self.datasvc = datasvc

    def register(self):
        self.hooks = RegisterHooks(self.datasvc)
        self.hooks.register()
        self.actions = RegisterActions(self.datasvc)
        self.actions.register()

    def get_action_details(self, app, action_name):
        return self.actions.actionmap[app][action_name] if app in self.actions.actionmap and action_name in self\
            .actions.actionmap[app] else None

    def async(self, app, action_name, params):
        action = self.actions.actionmap[app][action_name]['callable']
        job = self.datasvc.jobsvc.NewJob("{}.{}".format(app, action_name), "Action", {
            "application": app,
            "params": params
        })
        job_id = str(job.job_id)
        run_job.apply_async((self.datasvc.settings, action, {'params': params}), task_id=job_id)
        return {"action": action_name, "job_id": job_id, "status": "async/running"}


DefaultHookMap = {
    'BUILD_UPLOAD_SUCCESS': None,
    'GITDEPLOY_INIT_PRE': None,
    'GITDEPLOY_INIT_POST': None,
    'GITDEPLOY_DEINIT_PRE': None,
    'GITDEPLOY_DEINIT_POST': None,
    'GITDEPLOY_COMMIT_DIFF': None,
    'AUTO_DEPLOYMENT_START': None,
    'AUTO_DEPLOYMENT_BATCH_BEGIN': None,
    'AUTO_DEPLOYMENT_BATCH_DONE': None,
    'AUTO_DEPLOYMENT_COMPLETE': None,
    'AUTO_DEPLOYMENT_FAILED': None
}

class RegisterHooks:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.hookmap = dict()

    def register(self):
        #first load all defaults
        apps = self.datasvc.appsvc.GetApplications()
        for app in apps:
            self.hookmap[app] = {k: DefaultHookMap[k] for k in DefaultHookMap}  # need a new dict for each app
        from pkg_resources import iter_entry_points
        for obj in iter_entry_points(group="elita.modules", name="register_hooks"):
            hooks = (obj.load())()  # returns: { app: { "HOOK_NAME": <callable> } }
            for app in hooks:
                if app in apps:
                    for a in hooks[app]:
                        self.hookmap[app][a] = hooks[app][a]
                else:
                    logging.debug("register: WARNING: unknown application '{}'".format(app))
            logging.debug("HookMap: {}".format(self.hookmap))

    def run_hook(self, app, name, args):
        # Hooks are always triggered in an async context, so there's no need to spawn another celery task
        hook = self.hookmap[app][name]
        if hook is None:
            return "none"
        args['datasvc'] = self.datasvc
        return hook(**args)


class RegisterActions:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.actionmap = dict()

    def register(self):
        logging.debug("register")

        from pkg_resources import iter_entry_points
        apps = self.datasvc.appsvc.GetApplications()

        for obj in iter_entry_points(group="elita.modules", name="register_actions"):
            logging.debug("register: found obj: {}".format(obj))
            actions = (obj.load())()
            logging.debug("actions: {}".format(actions))
            for app in actions:
                if app not in apps:
                    logging.debug("WARNING: application not found: {}".format(app))
                else:
                    if app not in self.actionmap:
                        self.actionmap[app] = dict()
                    for a in actions[app]:
                        action_name = a['callable'].__name__
                        self.actionmap[app][action_name] = a
                        logging.debug("NewAction: app: {}; action_name: {}; params: {}".format(app, action_name, a['params']))
                        params = a['params'].keys()
                        self.datasvc.jobsvc.NewAction(app, action_name, params)
