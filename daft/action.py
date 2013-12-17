import scorebig
import models
import util

__author__ = 'bkeroack'

MODULES = [scorebig]

class ActionService:
    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.hooks = RegisterHooks(self.datasvc)
        self.hooks.register()
        self.actions = RegisterActions(self.datasvc)
        self.actions.register()


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
        self.modules = MODULES

    def register(self):
        for m in self.modules:
            for app in m.register_apps():
                hooks = m.register_hooks()
                for a in hooks[app]:
                    self.hookmap[app] = DefaultHookMap
                    self.hookmap[app][a] = hooks[app][a]
        util.debugLog(self, "HookMap: {}".format(self.hookmap))

    def run_hook(self, app, name, **kwargs):
        util.debugLog(self, "run_hook: app: {}; name: {}; kwargs: {}".format(app, name, kwargs))
        return self.hookmap[app][name](self.datasvc, **kwargs).go()


class RegisterActions:
    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.modules = MODULES

    def register(self):
        util.debugLog(self, "register")
        for m in self.modules:
            util.debugLog(self, "module: {}".format(m))
            actions = m.register_actions()
            util.debugLog(self, "actions: {}".format(actions))
            for app in actions:
                for a in actions[app]:
                    action_name = a.__name__
                    params = a.params()
                    util.debugLog(self, "NewAction: app: {}; action_name: {}; params: {}".format(app, action_name, params))
                    self.datasvc.NewAction(app, action_name, params, a)
