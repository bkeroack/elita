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
        if self.validate_token():
            util.debugLog(self, "valid token")
            self.userobj = models.root['app_root']['global']['tokens'][self.token]
        util.debugLog(self, "userobj: {}".format(self.userobj))

    def validate_token(self):
        return self.token in models.root['app_root']['global']['tokens']

    def get_permissions(self, app):
        if self.userobj:
            if self.userobj.name == 'admin':
                return "read;write"
            elif app in self.userobj.permissions:
                return self.userobj.permissions[app]
        return ""


class TokenUtils:

    @staticmethod
    def get_token_by_username(username):
        tc = models.root['app_root']['global']['tokens']
        for t in tc:
            if tc[t].username == username:
                return tc[t].token
        return None

    @staticmethod
    def new_token(username):
        if username in models.root['app_root']['global']['users']:
            tokenobj = models.Token(username)
            models.root['app_root']['global']['tokens'][username] = tokenobj
            return tokenobj.token
        return None
