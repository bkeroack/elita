__author__ = 'bkeroack'

import fnmatch
import logging

import elita.util
from elita.models import User

class ValidatePermissionsObject:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, permissions):
        self.permissions = permissions

    def verify_top_dict(self):
        return isinstance(self.permissions, dict)

    def verify_top_keys(self):
        if self.permissions:
            for t in self.permissions:
                try:
                    assert (t == "apps") or (t == "actions") or (t == "servers")
                except AssertionError:
                    return False
            return True
        else:
            return False

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
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, usersvc, token, datasvc=None):
        self.usersvc = usersvc
        self.token = token
        self.userobj = False
        self.valid_token = False
        self.datasvc = datasvc
        self.username = ""
        if self.validate_token():
            self.valid_token = True
            logging.debug("valid token")
            self.username = self.usersvc.GetUserFromToken(token)
            logging.debug("username: {}".format(self.username))

    def validate_token(self):
        return self.token in self.usersvc.GetAllTokens()

    def get_allowed_apps(self, username=None):
        '''Returns list of tuples: (appname, permissions ('read;write'))'''
        if not self.valid_token:
            return {}
        if not username:
            username = self.username
        user = self.usersvc.GetUser(username)
        assert self.datasvc is not None
        assert 'permissions' in user
        permissions = user['permissions']
        apps = self.datasvc.appsvc.GetApplications()
        apps.append('_global') #not returned by GetApplications()
        logging.debug("get_allowed_apps: username: {}".format(username))
        raw_app_list = [(fnmatch.filter(apps, a),
                 permissions['apps'][a]) for a in permissions['apps']]
        logging.debug("get_allowed_apps: raw_app_list: {}".format(raw_app_list))
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
        user = self.usersvc.GetUser(username)
        assert self.datasvc is not None
        assert 'permissions' in user
        permissions = user['permissions']
        logging.debug("get_allowed_actions: username: {}".format(username))
        allowed_actions = dict()
        for a in permissions['actions']:
            app_list = fnmatch.filter(self.datasvc.appsvc.GetApplications(), a)
            for app in app_list:
                app_actions_allowed = set()
                for action_pattern in permissions['actions'][a]:
                    app_actions_allowed.update(tuple(fnmatch.filter(self.datasvc.jobsvc.GetAllActions(app),
                                                               action_pattern)))
                allowed_actions[app] = list(app_actions_allowed)
        return allowed_actions

    def get_allowed_servers(self, username):
        '''Returns list'''
        user = self.usersvc.GetUser(username)
        assert self.datasvc is not None
        assert 'permissions' in user
        assert 'servers' in user['permissions']
        logging.debug("get_allowed_servers: username: {}".format(username))
        servers = self.datasvc.serversvc.GetServers()
        return ([fnmatch.filter(servers, s) for s in user['permissions']['servers']])

    def get_action_permissions(self, app, action):
        logging.debug("get_action_permissions: {}: {}".format(app, action))
        if self.valid_token and self.username in self.usersvc.GetUsers():
            user = self.usersvc.GetUser(self.username)
            assert 'permissions' in user
            permissions = user['permissions']
            if self.username == 'admin':
                logging.debug("returning admin permissions")
                return "execute"
            if app in permissions['actions']:
                logging.debug("{} in permissions['actions']".format(app))
                if action in permissions['actions'][app]:
                    return permissions['actions'][app][action]
                if '*' in permissions['actions'][app]:
                    return permissions['actions'][app]['*']
            if "*" in permissions['actions']:
                logging.debug("* in permissions['actions']")
                if action in permissions['actions']['*']:
                    return permissions['actions']['*'][action]
                if '*' in permissions['actions']['*']:
                    return permissions['actions']['*']['*']
            logging.debug("returning deny")
            return "deny"

    def get_app_permissions(self, app):
        logging.debug("get_permissions: app: {}".format(app))
        if self.valid_token and self.username in self.usersvc.GetUsers():
            user = self.usersvc.GetUser(self.username)
            if user['username'] == 'admin':
                logging.debug("returning admin permissions")
                return "read;write"
            elif "*" in user['permissions']['apps']:
                logging.debug("found wildcard perms")
                return user['permissions']['apps']['*']
            elif app in user['permissions']['apps']:
                logging.debug("returning perms: {}".format(user['permissions']['apps'][app]))
                return user['permissions']['apps'][app]
        logging.debug("invalid user or token: {}; {}".format(self.username, self.token))
        return ""

    def validate_pw(self, username, password):
        userobj = User(self.usersvc.GetUser(username))
        return userobj.validate_password(password)


