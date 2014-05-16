__author__ = 'bkeroack'

import util
import fnmatch

class ValidatePermissionsObject:
    def __init__(self, permissions):
        self.permissions = permissions

    def verify_top_dict(self):
        return isinstance(self.permissions, dict)

    def verify_top_keys(self):
        for t in self.permissions:
            try:
                assert (t == "apps") or (t == "actions") or (t == "servers")
            except AssertionError:
                return False
        return True

    def verify_perm_keys(self):
        #perm keys can be basically anything
        return True

    def verify_iterable(self):
        for t in self.permissions:
            for p in self.permissions[t]:
                try:
                    _ = (e for e in p)  # check if iterable
                except TypeError:
                    return False
        return True

    def run(self):
        if self.verify_top_dict():
            if self.verify_top_keys():
                if self.verify_perm_keys():
                    if self.verify_iterable():
                        return True
        return False


class UserPermissions:
    def __init__(self, usersvc, token, datasvc=None):
        self.usersvc = usersvc
        self.token = token
        self.userobj = False
        self.valid_token = False
        self.datasvc = datasvc
        if self.validate_token():
            self.valid_token = True
            util.debugLog(self, "valid token")
            self.username = self.usersvc.GetUserFromToken(token)
            util.debugLog(self, "username: {}".format(self.username))

    def validate_token(self):
        return self.token in self.usersvc.GetAllTokens()

    def get_allowed_apps(self, username):
        '''Returns list of tuples: (appname, permissions ('read;write'))'''
        userobj = self.usersvc.GetUser(username)
        assert self.datasvc is not None
        apps = self.datasvc.appsvc.GetApplications()
        apps.append('_global') #not returned by GetApplications()
        util.debugLog(self, "get_allowed_apps: username: {}".format(username))
        raw_app_list = [(fnmatch.filter(apps, a),
                 userobj.permissions['apps'][a]) for a in userobj.permissions['apps']]
        util.debugLog(self, "get_allowed_apps: raw_app_list: {}".format(raw_app_list))
        perms_dict = dict()
        for l in raw_app_list:  # coalesce the list, really wish this could be a dict comprehension
            perm = l[1]
            apps = l[0]
            if perm in perms_dict:
                perms_dict[perm].update(apps)
            else:
                perms_dict[perm] = set(apps)
        return {k: list(perms_dict[k]) for k in perms_dict}

    def get_allowed_actions(self, username):
        '''Returns list of tuples: (appname, actionname). If present, 'execute' permission is implicit'''
        userobj = self.usersvc.GetUser(username)
        assert self.datasvc is not None
        util.debugLog(self, "get_allowed_actions: username: {}".format(username))
        allowed_actions = dict()
        for a in userobj.permissions['actions']:
            app_list = fnmatch.filter(self.datasvc.appsvc.GetApplications(), a)
            for app in app_list:
                app_actions_allowed = set()
                for action_pattern in userobj.permissions['actions'][a]:
                    app_actions_allowed.update(tuple(fnmatch.filter(self.datasvc.jobsvc.GetAllActions(app),
                                                               action_pattern)))
                allowed_actions[app] = list(app_actions_allowed)
        return allowed_actions

    def get_allowed_servers(self, username):
        '''Returns list'''
        userobj = self.usersvc.GetUser(username)
        assert self.datasvc is not None
        util.debugLog(self, "get_allowed_servers: username: {}".format(username))
        servers = self.datasvc.serversvc.GetServers()
        return ([fnmatch.filter(servers, s) for s in userobj.permissions['servers']])

    def get_action_permissions(self, app, action):
        util.debugLog(self, "get_action_permissions: {}: {}".format(app, action))
        if self.valid_token and self.username in self.usersvc.GetUsers():
            userobj = self.usersvc.GetUser(self.username)
            if userobj.name == 'admin':
                util.debugLog(self, "returning admin permissions")
                return "execute"
            if app in userobj.permissions['actions']:
                util.debugLog(self, "{} in permissions['actions']".format(app))
                if action in userobj.permissions['actions'][app]:
                    return userobj.permissions['actions'][app][action]
                if '*' in userobj.permissions['actions'][app]:
                    return userobj.permissions['actions'][app]['*']
            if "*" in userobj.permissions['actions']:
                util.debugLog(self, "* in permissions['actions']")
                if action in userobj.permissions['actions']['*']:
                    return userobj.permissions['actions']['*'][action]
                if '*' in userobj.permissions['actions']['*']:
                    return userobj.permissions['actions']['*']['*']
            util.debugLog(self, "returning deny")
            return "deny"

    def get_app_permissions(self, app):
        util.debugLog(self, "get_permissions: app: {}".format(app))
        if self.valid_token and self.username in self.usersvc.GetUsers():
            userobj = self.usersvc.GetUser(self.username)
            if userobj.name == 'admin':
                util.debugLog(self, "returning admin permissions")
                return "read;write"
            elif "*" in userobj.permissions['apps']:
                util.debugLog(self, "found wildcard perms")
                return userobj.permissions['apps']['*']
            elif app in userobj.permissions['apps']:
                util.debugLog(self, "returning perms: {}".format(userobj.permissions['apps'][app]))
                return userobj.permissions['apps'][app]
        return ""

    def validate_pw(self, username, password):
        userobj = self.usersvc.GetUser(username)
        return userobj.validate_password(password)


