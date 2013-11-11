__author__ = 'bkeroack'

import models
import util

def ValidatePermissionsObject(permissions):
    if isinstance(permissions, dict):
        for p in permissions:
            try:
                _ = (e for e in p)  # check if iterable
            except TypeError:
                return False
        return True
    return False



class UserPermissions:
    def __init__(self, token):
        self.token = token
        self.userobj = False
        self.valid_token = False
        if self.validate_token():
            self.valid_token = True
            util.debugLog(self, "valid token")
            self.username = models.root['app_root']['global']['tokens'][self.token].username
            util.debugLog(self, "username: {}".format(self.username))

    def validate_token(self):
        return self.token in models.root['app_root']['global']['tokens']

    def get_permissions(self, app):
        util.debugLog(self, "get_permissions: app: {}".format(app))
        if self.valid_token and self.username in models.root['app_root']['global']['users']:
            util.debugLog(self, "get_permissions: username in users")
            userobj = models.root['app_root']['global']['users'][self.username]
            if userobj.name == 'admin':
                return "read;write"
            elif "*" in userobj.permissions:
                return userobj.permissions['*']
            elif app in userobj.permissions:
                return userobj.permissions[app]
        return ""

    def validate_pw(self, username, password):
        userobj = models.root['app_root']['global']['users'][username]
        return userobj.validate_password(password)


