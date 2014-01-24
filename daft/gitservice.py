import requests
from slugify import slugify
import tempfile
import os
import sh

import util
import salt_control
import builds

__author__ = 'bkeroack'

class ValidRepoTypes:
    type_names = ['github', 'bitbucket']

class BitBucketData:
    api_base_url = 'https://api.bitbucket.org/2.0'

class GitHubData:
    api_base_url = 'https://github.com'

#callables for async execution
def create_bitbucket_repo(datasvc, gitprovider, name, application):
    bbsvc = BitBucketRepoService(gitprovider, datasvc.settings)
    resp = bbsvc.create_repo(name)
    uri = bbsvc.get_ssh_uri(name)
    if uri:
        bbsvc.setup_gitdeploy_dir(name, application)
        datasvc.gitsvc.UpdateGitRepo(name, {'uri': uri})
    else:
        util.debugLog(create_bitbucket_repo, "ERROR: uri for gitrepo not found!")
        resp['error'] = {'message': 'error getting uri!, local master not initialized!'}
    return resp

def create_github_repo(datasvc, gitprovider, name, application):
    return {'error': 'not implemented'}

def create_repo_callable_from_type(repo_type):
    if repo_type not in ValidRepoTypes.type_names:
        return None
    return create_bitbucket_repo if repo_type == 'bitbucket' else create_github_repo

def delete_repo_callable_from_type(repo_type):
    if repo_type not in ValidRepoTypes.type_names:
        return None
    return delete_bitbucket_repo if repo_type == 'bitbucket' else delete_github_repo

def delete_bitbucket_repo(datasvc, gitprovider, name):
    bbrs = BitBucketRepoService(gitprovider, datasvc.settings)
    return bbrs.delete_repo(name)

def delete_github_repo(datasvc, gitprovider, name):
    return {'error': 'not implemented'}

def create_gitdeploy(datasvc, gitdeploy):
    gdm = GitDeployManager(gitdeploy, datasvc.settings)
    gdm.add_sls()
    return "done"

def initialize_gitdeploy(datasvc, gitdeploy, server_list):
    gdm = GitDeployManager(gitdeploy, datasvc.settings)
    return gdm.initialize(server_list)

class GitRepoService:
    def __init__(self, gitprovider, settings):
        self.gp_type = gitprovider['type']
        self.settings = settings
        self.auth = gitprovider['auth']
        self.base_url = BitBucketData.api_base_url if self.gp_type == 'bitbucket' else GitHubData.api_base_url

    def create_repo(self, name):
        util.debugLog(self, "create_repo not implemented")

    def setup_gitdeploy_dir(self, name, application, uri):
        '''create master gitdeploy directory and initialize with git'''
        root = self.settings['daft.gitdeploy.dir']
        path = "{}/{}".format(root, application)
        if not os.path.isdir(path):
            os.mkdir(path)
        path += "/{}".format(name)
        if not os.path.isdir(path):
            os.mkdir(path)
        git = sh.git.bake(_cwd=path)
        res = git.init()
        util.debugLog(self, "setup_gitdeploy_dir: git init: {}".format(res))
        res = git.remote("add origin ssh://{}".format(uri))
        util.debugLog(self, "setup_gitdeploy_dir: git remote add origin: {}".format(res))


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

    def delete_repo(self, name):
        util.debugLog(self, "Deleting repo: {}".format(name))
        slug=slugify(name)
        username = self.auth['username']
        password = self.auth['password']
        r = requests.delete("{}/repositories/{}/{}".format(self.base_url, username, slug), auth=(username, password))
        try:
            resp = r.json()
        except:
            resp = r.text
        return resp

    def get_ssh_uri(self, name):
        util.debugLog(self, "getting clone URI for {}".format(name))
        slug = slugify(name)
        username = self.auth['username']
        password = self.auth['password']
        r = requests.get("{}/repositories/{}/{}".format(self.base_url, username, slug), auth=(username, password))
        try:
            resp = r.json()
        except:
            return None
        for l in resp['links']['clone']:
            if l['name'] == "ssh":
                return l['href'][6:]  # chop off leading 'ssh://'
        return None

class GitDeployManager:
    def __init__(self, gitdeploy, settings):
        self.gitdeploy = gitdeploy
        self.settings = settings
        self.sc = salt_control.SaltController(self.settings)
        self.rc = salt_control.RemoteCommands(self.sc)

    def initialize(self, server_list):
        cr = self.create_remote_dir(server_list)
        pku, pkr = self.push_keypair(server_list)
        cl = self.clone_repo(server_list)
        return {
            'create_remote_dir': cr,
            'push_public_key': pku,
            'push_private_key': pkr,
            'clone_repo': cl
        }

    def add_sls(self):
        self.sc.new_gitdeploy_yaml(self.gitdeploy)

    def create_remote_dir(self, server_list):
        path = self.gitdeploy['location']['path']
        res = self.rc.create_directory(server_list, path)
        util.debugLog(self, 'create_remote_dir on servers: {}: resp: {}'.format(server_list, res))
        return res

    def push_keypair(self, server_list):
        f_pub, tf_pub = tempfile.mkstemp(text=True)
        f_pub.write(self.gitdeploy['location']['git_repo']['keypair']['public_key'])
        f_pub.close()
        f_priv, tf_priv = tempfile.mkstemp(text=True)
        f_priv.write(self.gitdeploy['location']['git_repo']['keypair']['private_key'])
        f_priv.close()
        res_pub = self.rc.push_key(server_list, tf_pub, self.gitdeploy['name'], '.pub')
        util.debugLog(self, "push_keypair: push pub resp: {}".format(res_pub))
        res_priv = self.rc.push_key(server_list, tf_priv, self.gitdeploy['name'], '')
        util.debugLog(self, "push_keypair: push priv resp: {}".format(res_priv))
        os.unlink(tf_pub)
        os.unlink(tf_priv)
        return res_pub, res_priv

    def clone_repo(self, server_list):
        uri = self.gitdeploy['location']['git_repo']['uri']
        dest = self.gitdeploy['location']['path']
        res = self.rc.clone_repo(server_list, uri, dest)
        util.debugLog(self, "clone_repo: resp: {}".format(res))
        return res

    def get_path(self):
        appname = self.gitdeploy['application']
        gitrepo_name = self.gitdeploy['location']['git_repo']['name']
        root = self.settings['daft.gitdeploy.dir']
        return "{}/{}/{}".format(root, appname, gitrepo_name)

    def decompress_to_repo(self, package_doc):
        path = self.get_path()
        util.debugLog(self, "commit_to_repo_and_push: decompressing {} to {}".format(package_doc['filename'], path))
        bf = builds.BuildFile(package_doc)
        bf.decompress(path)

    def add_files_to_repo(self):
        util.debugLog(self, "commit_to_repo_and_push: git add")
        path = self.get_path()
        git = sh.git.bake(_cwd=path)
        return git.add('-A')

    def commit_to_repo(self, build_name):
        util.debugLog(self, "commit_to_repo_and_push: git commit")
        path = self.get_path()
        git = sh.git.bake(_cwd=path)
        return git.commit(m=build_name)

    def push_repo(self):
        util.debugLog(self, "commit_to_repo_and_push: git push")
        path = self.get_path()
        git = sh.git.bake(_cwd=path)
        return git.push()


