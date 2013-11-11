from persistent.mapping import PersistentMapping
import datetime
import hashlib
import uuid
import base64

from . import util

# URL model:
# root/app/
# root/app/{app_name}/builds/
# root/app/{app_name}/builds/{build_name}
# root/app/{app_name}/environments/
# root/app/{app_name}/environments/{env_name}/deployments
# root/app/{app_name}/environments/{env_name}/deployments/{deployment_id}
# root/app/{app_name}/environments/{env_name}/servers
# root/app/{app_name}/environemnt/{env_name}/servers/{server_name}


#global handle for the root object, so all views have access
root = None

class SupportedFileType:
    TarGz = 'tar.gz'
    TarBz2 = 'tar.bz2'
    Zip = 'zip'
    types = [TarBz2, TarGz, Zip]
    

class BaseModelObject(PersistentMapping):
    def __init__(self):
        PersistentMapping.__init__(self)
        self.created_datetime = datetime.datetime.now()


class Server:
    env_name = None

class Deployment:
    env_name = None

class Environment:
    app_name = None

class EnvironmentContainer(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class Build(BaseModelObject):
    def __init__(self, app_name, build_name, subsys=[]):
        BaseModelObject.__init__(self)
        self.app_name = app_name
        self.build_name = build_name
        self.subsys = subsys
        self.stored = False
        self.files = dict()  # { filename: filetype }
        self.master_file = None  # original uploaded file
        self.packages = dict()  # { package_type: {'filename': filename, 'file_type': file_type}}

class BuildDetail(BaseModelObject):
    def __init__(self, buildobj):
        BaseModelObject.__init__(self)
        self.buildobj = buildobj

class BuildContainer(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class Subsystem(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class SubsystemContainer(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class Action(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class ActionContainer(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class Application(BaseModelObject):
    def __init__(self, app_name):
        BaseModelObject.__init__(self)
        self.app_name = app_name

class User(BaseModelObject):
    def __init__(self, name, pw, permissions, salt):
        BaseModelObject.__init__(self)
        util.debugLog(self, "user: {}, pw: {}".format(name, pw))
        self.salt = salt
        util.debugLog(self, "got salt: {}".format(self.salt))
        self.name = name
        self.hashed_pw = self.hash_pw(pw)
        util.debugLog(self, "hashed pw: {}".format(self.hashed_pw))
        self.permissions = permissions

    def hash_pw(self, pw):
        return base64.urlsafe_b64encode(hashlib.sha512(pw + self.salt).hexdigest())

    def validate_password(self, pw):
        return self.hashed_pw == self.hash_pw(pw)

class UserContainer(BaseModelObject):
    def __init__(self):
        BaseModelObject.__init__(self)
        self.salt = base64.urlsafe_b64encode((uuid.uuid4().bytes))

class TokenContainer(BaseModelObject):
    def __init__(self):
        BaseModelObject.__init__(self)
        self.usermap = dict()  # for quick token lookup by user

    def __setitem__(self, key, value):
        BaseModelObject.__setitem__(self, key, value)
        if value.username in self.usermap:
            self.usermap[value.username].append(value)
        else:
            self.usermap[value.username] = [value]

    def get_tokens_by_username(self, username):
        return self.usermap[username] if username in self.usermap else []

    def remove_token(self, token):
        username = self[token].username
        for t in self.usermap[username]:
            if t.token == token:
                self.usermap[username].remove(t)
        del self[token]

    def new_token(self, username):
        tokenobj = Token(username)
        self[tokenobj.token] = tokenobj
        return tokenobj.token

class Token(BaseModelObject):
    def __init__(self, username):
        BaseModelObject.__init__(self)
        self.username = username
        self.token = base64.urlsafe_b64encode(hashlib.sha256(uuid.uuid4().bytes).hexdigest())[:-2]  # strip '=='

class ApplicationContainer(BaseModelObject):
    pass

class GlobalContainer(BaseModelObject):
    pass

class RootApplication(BaseModelObject):
    pass


def appmaker(zodb_root):
    global root
    if not 'app_root' in zodb_root:
        app_root = RootApplication()
        zodb_root['app_root'] = app_root
        zodb_root['app_root']['app'] = ApplicationContainer()
        zodb_root['app_root']['global'] = GlobalContainer()
        uc = UserContainer()
        zodb_root['app_root']['global']['users'] = uc
        zodb_root['app_root']['global']['users']['admin'] = User("admin", "daft", {"_global": "read;write"}, uc.salt)
        zodb_root['app_root']['global']['tokens'] = TokenContainer()
        tk = Token('admin')
        zodb_root['app_root']['global']['tokens'][tk.token] = tk
        import transaction
        transaction.commit()
    root = zodb_root
    return zodb_root['app_root']
