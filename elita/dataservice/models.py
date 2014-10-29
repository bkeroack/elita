import hashlib
import uuid
import base64
import bson

import elita
from elita.crypto import keypair

import elita.util
import elita.util.type_check
import elita.elita_exceptions


# URL model:
# root/app/
# root/app/{app_name}/builds/
# root/app/{app_name}/builds/{build_name}
# root/app/{app_name}/environments/
# root/app/{app_name}/environments/{env_name}/deployments
# root/app/{app_name}/environments/{env_name}/deployments/{deployment_id}
# root/app/{app_name}/environments/{env_name}/servers
# root/app/{app_name}/environemnt/{env_name}/servers/{server_name}


class SupportedFileType:
    TarGz = 'tar.gz'
    TarBz2 = 'tar.bz2'
    Zip = 'zip'
    types = [TarBz2, TarGz, Zip]


class GenericDataModel:
    __metaclass__ = elita.util.LoggingMetaClass

    default_values = {}

    def __init__(self, doc):
        self.set_defaults()
        if doc is not None:
            for k in doc:
                if k == '_id':
                    self.created_datetime = doc['_id'].generation_time
                elif k[0] != '_':
                    self.set_data(k, doc[k])
        self.init_hook()

    def init_hook(self):
        pass

    def set_defaults(self):
        for k in self.default_values:
            if not hasattr(self, k):
                setattr(self, k, self.default_values[k])

    def set_data(self, key, value):
        self._set_data(key, value)

    def _set_data(self, key, value):
        setattr(self, key, value)

    def update_values(self, doc):
        for k in doc:
            if hasattr(self, k):
                setattr(self, k, doc[k])

    def get_doc(self):
        return {k: getattr(self, k) for k in self.default_values}


class KeyPair(GenericDataModel):
    default_values = {
        "name": None,
        "attributes": dict(),
        "key_type": None,  # git | salt
        "private_key": None,
        "public_key": None
    }

    def init_hook(self):
        if self.key_type not in ("git", "salt"):
            raise elita.elita_exceptions.InvalidKeyPairType
        kp = keypair.KeyPair(self.private_key, self.public_key)
        try:
            kp.verify_public()
        except:
            raise elita.elita_exceptions.InvalidPublicKey
        try:
            kp.verify_private()
        except:
            raise elita.elita_exceptions.InvalidPrivateKey

class Server(GenericDataModel):
    default_values = {
        "name": None,
        "server_type": None,
        "status": None,
        "environment": None,
        "attributes": dict(),
        "gitdeploys": [bson.DBRef("", None)],
        "salt_key": bson.DBRef("", None)
    }

class Environment(GenericDataModel):
    default_values = {
        "environments": None
    }

class GitProvider(GenericDataModel):
    default_values = {
        'name': None,
        'type': None,
        'auth': {
            'username': None,
            'password': None
        }
    }

class GitRepo(GenericDataModel):
    default_values = {
        'name': None,
        'application': None,
        'last_build': None,
        'uri': None,
        'keypair': bson.DBRef("", None),
        'gitprovider': bson.DBRef("", None)
    }

class GitDeploy(GenericDataModel):
    default_values = {
        'name': None,
        'application': None,
        'package': 'master',
        'servers': list(),
        'attributes': dict(),
        'deployed_build': None,
        'options': {
            'favor': 'ours',
            'ignore-whitespace': 'true',
            'gitignore': list()
        },
        'actions': {
            'prepull': [],
            'postpull': []
        },
        'location': {
            'path': None,
            'git_repo': bson.DBRef("", None),
            'default_branch': None,
            'current_branch': None,
            'current_rev': None
        }
    }

class Deployment(GenericDataModel):
    '''
    There are two "phases" to a deployment:
        - Phase 1: processing of gitdeploys (applying packages, adding/committing/pushing to gitprovider, determining
            changes)
        - Phase 2: Performing salt states/git pull on target machines. Can be broken up into an arbitrary number of
            batches
    '''
    default_values = {
        'name': None,  # "name" for consistency w/ other models, even though it's really id
        'application': None,
        'build_name': None,
        'environments': None,
        'groups': None,
        'servers': None,
        'gitdeploys': None,
        'username': None,
        'options': dict(),  # pauses, divisor
        'status': None,
        'commits': dict(),    # { gitrepo_name: commit_hash }
        'progress': {
            'currently_on': None,
            'phase1': {
                'gitrepos': dict()
            },
            'phase2': dict()
        },
        'job_id': None
    }

class Build(GenericDataModel):
    default_values = {
        'build_name': None,
        'app_name': None,
        'files': list(),
        'stored': False,
        'master_file': None,
        'packages': dict(),
        'attributes': dict()
    }


class Action:
    def __init__(self, app_name, action_name, params, job_datasvc):
        self.app_name = app_name
        self.action_name = action_name
        self.params = params
        self.job_datasvc = job_datasvc

    def execute(self, params):
        return self.job_datasvc.ExecuteAction(self.app_name, self.action_name, params)

    def details(self):
        return self.job_datasvc.GetAction(self.app_name, self.action_name)

class Application(GenericDataModel):
    default_values = {
        'app_name': None
    }

class User(GenericDataModel):
    default_values = {
        'username': None,
        'password': None,
        'hashed_pw': None,
        'salt': None,
        'attributes': dict(),
        'permissions': {
            'apps': {},
            'actions': {},
            'servers': []
        }
    }

    def init_hook(self):
        assert self.hashed_pw or self.password
        if self.password:   # new or changed password
            self.salt = base64.urlsafe_b64encode(uuid.uuid4().bytes)
            self.hashed_pw = self.hash_pw(self.password)
            self.password = None

    def hash_pw(self, pw):
        assert pw is not None
        return base64.urlsafe_b64encode(hashlib.sha512(pw + self.salt).hexdigest())

    def validate_password(self, pw):
        return self.hashed_pw == self.hash_pw(pw)


#dummy model. Values are computed for each request
class UserPermissions(GenericDataModel):
    default_values = {
        'username': None,
        'applications': None,
        'actions': None,
        'servers': None
    }

class Token(GenericDataModel):
    default_values = {
        'username': None,
        'token': None
    }

    def init_hook(self):
        self.token = base64.urlsafe_b64encode(hashlib.sha256(uuid.uuid4().bytes).hexdigest())[:-2] \
            if self.token is None else self.token

class Job(GenericDataModel):
    default_values = {
        'status': 'running',
        'name': None,
        'job_type': None,
        'data': None,
        'completed_datetime': None,
        'duration_in_seconds': None,
        'attributes': None,
        'job_id': None
    }

    def init_hook(self):
        self.job_id = uuid.uuid4() if self.job_id is None else self.job_id

class Group(GenericDataModel):
    default_values = {
        'application': None,
        'name': None,
        'description': None,
        'gitdeploys': list(),
        'attributes': dict(),
        'rolling_deploy': False
    }

class PackageMap(GenericDataModel):
    default_values = {
        'application': None,
        'name': None,
        'attributes': dict(),
        'packages': dict()
    }
    # Example packages field:
    # packages = {
    #     'package_name': [{
    #             'patterns': ["foo/bar/*"],
    #             'prefix': "foobar/",
    #             'remove_prefix': "bar/"
    #     }]
    # }

class GenericContainer:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, doc):
        self.name = doc['name']
        self.parent = doc['parent']
        self.created_datetime = doc['_id'].generation_time if '_id' in doc else None


class BuildContainer(GenericContainer):
    pass

class ActionContainer(GenericContainer):
    pass

class UserContainer(GenericContainer):
    pass

class TokenContainer(GenericContainer):
    pass

class ApplicationContainer(GenericContainer):
    pass

class GlobalContainer(GenericContainer):
    pass

class JobContainer(GenericContainer):
    pass

class ServerContainer(GenericContainer):
    pass

class GitProviderContainer(GenericContainer):
    pass

class GitRepoContainer(GenericContainer):
    pass

class GitDeployContainer(GenericContainer):
    pass

class DeploymentContainer(GenericContainer):
    pass

class KeyPairContainer(GenericContainer):
    pass

class GroupContainer(GenericContainer):
    pass

class PackageMapContainer(GenericContainer):
    pass

class Root(GenericContainer):
    pass




