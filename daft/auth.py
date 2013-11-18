__author__ = 'bkeroack'

import models
import util
import re

class ValidatePermissionsObject:
    def __init__(self, permissions):
        self.permissions = permissions

    def verify_top_dict(self):
        return isinstance(self.permissions, dict)

    def verify_top_keys(self):
        for t in self.permissions:
            try:
                assert (t == "apps") or (t == "actions")
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
    def __init__(self, token):
        self.token = token
        self.userobj = False
        self.valid_token = False
        self.ds = models.DataService()
        if self.validate_token():
            self.valid_token = True
            util.debugLog(self, "valid token")
            self.username = models.root['app_root']['global']['tokens'][self.token].username
            util.debugLog(self, "username: {}".format(self.username))

    def validate_token(self):
        return self.token in models.root['app_root']['global']['tokens']

    def get_action_permissions(self, app, action):
        util.debugLog(self, "get_action_permissions: {}: {}".format(app, action))
        if self.valid_token and self.username in self.ds.GetUsers():
            userobj = self.ds.GetUser(self.username)
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
        if self.valid_token and self.username in self.ds.GetUsers():
            userobj = self.ds.GetUser(self.username)
            if userobj.name == 'admin':
                util.debugLog(self, "returning admin permissions")
                return "read;write"
            elif "*" in userobj.permissions['apps']:
                return userobj.permissions['*']
            elif app in userobj.permissions['apps']:
                util.debugLog(self, "returning perms: {}".format(userobj.permissions[app]))
                return userobj.permissions[app]
        return ""

    def validate_pw(self, username, password):
        userobj = models.root['app_root']['global']['users'][username]
        return userobj.validate_password(password)


