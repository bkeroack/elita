import requests
from slugify import slugify
import tempfile

import util
import salt_control

__author__ = 'bkeroack'

class ValidRepoTypes:
    type_names = ['github', 'bitbucket']

class BitBucketData:
    api_base_url = 'https://api.bitbucket.org/2.0'

class GitHubData:
    api_base_url = 'https://github.com'

#callables for async execution
def create_bitbucket_repo(datasvc, gitprovider, name):
    bbsvc = BitBucketRepoService(gitprovider)
    return bbsvc.create_repo(name)

def create_github_repo(datasvc, gitprovider, name):
    return {'error': 'not implemented'}

def create_repo_callable_from_type(repo_type):
    if repo_type not in ValidRepoTypes.type_names:
        return None
    return create_bitbucket_repo if repo_type == 'bitbucket' else create_github_repo

def initialize_gitdeploy(datasvc, gitdeploy):
    gdm = GitDeployManager(gitdeploy, datasvc.settings)
    gdm.initialize()

class GitRepoService:
    def __init__(self, gitprovider):
        self.gp_type = gitprovider['type']
        self.auth = gitprovider['auth']
        self.base_url = BitBucketData.api_base_url if self.gp_type == 'bitbucket' else GitHubData.api_base_url

    def create_repo(self, name):
        util.debugLog(self, "create_repo not implemented")

class GitHubRepoService(GitRepoService):
    pass

class BitBucketRepoService(GitRepoService):
    def create_repo(self, name):
        util.debugLog(self, "Creating repo: {}".format(name))
        slug = slugify(name)
        username = self.auth['username']
        password = self.auth['password']
        json_body = {
            'scm': 'git',
            'name': name,
            'is_private': 'true',
            'description': "Created by daft",
            'forking_policy': 'no_forks'
        }
        r = requests.post("{}/repositories/{}/{}".format(self.base_url, username, slug), data=json_body,
                          auth=(username, password))
        try:
            resp = r.json()
        except:
            resp = r.text
        return resp

class GitDeployManager:
    def __init__(self, gitdeploy, settings):
        self.gitdeploy = gitdeploy
        self.settings = settings
        self.sc = salt_control.SaltController(self.settings)
        self.rc = salt_control.RemoteCommands(self.sc)

    def initialize(self):
        self.add_sls()
        self.create_remote_dir()
        self.push_keypair()
        self.clone_repo()

    def add_sls(self):
        self.sc.add_gitdeploy_to_yaml(self.gitdeploy)

    def create_remote_dir(self):
        server = self.gitdeploy['server']['name']
        path = self.gitdeploy['location']['path']
        res = self.rc.create_directory(server, path)
        util.debugLog(self, 'create_remote_dir: resp: {}'.format(res))

    def push_keypair(self):
        f_pub, tf_pub = tempfile.mkstemp(text=True)
        f_pub.write(self.gitdeploy['location']['git_repo']['keypair']['public_key'])
        f_pub.close()
        f_priv, tf_priv = tempfile.mkstemp(text=True)
        f_priv.write(self.gitdeploy['location']['git_repo']['keypair']['private_key'])
        f_priv.close()
        server = self.gitdeploy['server']['name']
        res_pub = self.rc.push_key(server, tf_pub, self.gitdeploy['name'], '.pub')
        util.debugLog(self, "push_keypair: push pub resp: {}".format(res_pub))
        res_priv = self.rc.push_key(server, tf_priv, self.gitdeploy['name'], '')
        util.debugLog(self, "push_keypair: push priv resp: {}".format(res_priv))

    def clone_repo(self):
        server = self.gitdeploy['server']['name']
        uri = self.gitdeploy['location']['git_repo']['uri']
        dest = self.gitdeploy['location']['path']
        res = self.rc.clone_repo(server, uri, dest)
        util.debugLog(self, "clone_repo: resp: {}".format(res))
