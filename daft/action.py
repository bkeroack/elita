import scorebig
import models
import util

__author__ = 'bkeroack'

MODULES = [scorebig]

actionsvc = None

class ActionService:
    def __init__(self):
        self.hooks = RegisterHooks()
        self.hooks.register()
        self.actions = RegisterActions()
        self.actions.register()


class HookStub:
    def __init__(self):
        pass

    def go(self):
        return True

HookMap = dict()

DefaultHookMap = {
    'BUILD_UPLOAD_SUCCESS': HookStub
}

class RegisterHooks:
    def __init__(self):
        global HookMap
        self.modules = MODULES

    def register(self):
        global HookMap
        for m in self.modules:
            for app in m.register_apps():
                hooks = m.register_hooks()
                for a in hooks[app]:
                    HookMap[app] = DefaultHookMap
                    HookMap[app][a] = hooks[app][a]
        util.debugLog(self, "HookMap: {}".format(HookMap))

    def run_hook(self, app, name, **kwargs):
        util.debugLog(self, "run_hook: app: {}; name: {}; kwargs: {}".format(app, name, kwargs))
        return HookMap[app][name](models.DataService(), **kwargs).go()


class RegisterActions:
    def __init__(self):
        self.modules = MODULES
        self.datasvc = models.DataService()

    def register(self):
        for m in self.modules:
            actions = m.register_actions()
            for app in actions:
                for a in actions[app]:
                    action_name = a.__name__
                    params = a.params()
                    self.datasvc.NewAction(app, action_name, params, a)
