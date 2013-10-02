import scorebig

__author__ = 'bkeroack'


class ActionStub:
    def __init__(self):
        pass

    def go(self):
        return True

ActionMap = dict()

DefaultActionMap = {
    'BUILD_UPLOAD_SUCCESS': ActionStub
}

class RegisterActions:
    def __init__(self):
        global ActionMap
        self.modules = [scorebig]

    def register(self):
        global ActionMap
        for m in self.modules:
            for app in m.register_apps():
                actions = m.register_actions()
                for a in actions:
                    ActionMap[app] = DefaultActionMap
                    ActionMap[app][a] = actions[a]

    def run_action(self, app, name, **kwargs):
        return ActionMap[app][name](**kwargs).go()
