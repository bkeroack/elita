import requests
from slugify import slugify
import tempfile
import os
import shutil
import sh
import git
import copy
import socket
import logging

import elita.util
import elita.util.type_check
import salt_control
import elita.builds
import sshconfig

__author__ = 'bkeroack'

class ValidRepoTypes:
    type_names = ['github', 'bitbucket']

class BitBucketData:
    api_base_url = 'https://api.bitbucket.org/2.0'

class GitHubData:
    api_base_url = 'https://github.com'

#mongo does not allow dots in key names, so we have to replace dots in embedded yaml dict keys with this
EMBEDDED_YAML_DOT_REPLACEMENT = '#'

#callables for async execution
def create_bitbucket_repo(datasvc, gitprovider, name, application, keypair):
    bbsvc = BitBucketRepoService(gitprovider, datasvc.settings)
    resp = bbsvc.create_repo(name)
    uri = bbsvc.get_ssh_uri(name)
    if uri:
        logging.debug("got uri: {}".format(uri))
        alias = bbsvc.key_setup(name, application, keypair)
        alias_uri = uri.replace("bitbucket.org", alias)
        logging.debug("alias uri: {}".format(alias_uri))
        bbsvc.setup_gitdeploy_dir(name, application, alias_uri, empty=True)
        datasvc.gitsvc.UpdateGitRepo(application, name, {'uri': uri})
    else:
        logging.debug("ERROR: uri for gitrepo not found!")
        resp['error'] = {'message': 'error getting uri!, local master not initialized!'}
    return resp

def create_github_repo(datasvc, gitprovider, name, application, keypair):
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
    gdm = GitDeployManager(gitdeploy, datasvc)
    gdm.add_sls()
    return "done"

def remove_gitdeploy(datasvc, gitdeploy):
    gdm = GitDeployManager(gitdeploy, datasvc)
    gdm.rm_sls()
    datasvc.gitsvc.DeleteGitDeploy(gitdeploy['application'], gitdeploy['name'])
    return "done"

def initialize_gitdeploy(datasvc, gitdeploy, server_list):
    sc = salt_control.SaltController(datasvc)
    for s in server_list:
        if not sc.verify_connectivity(s):
            return {'error': "server '{}' not accessible via salt".format(s)}
    gdm = GitDeployManager(gitdeploy, datasvc)
    res = gdm.initialize(server_list)
    if 'servers' not in gitdeploy:
        gitdeploy['servers'] = list()
    sset = set(tuple(gitdeploy['servers']))
    for s in server_list:
        sset.add(s)
    datasvc.gitsvc.UpdateGitDeploy(gitdeploy['application'], gitdeploy['name'], {'servers': list(sset)})
    return res

def deinitialize_gitdeploy(datasvc, gitdeploy, server_list):
    sc = salt_control.SaltController(datasvc)
    for s in server_list:
        if not sc.verify_connectivity(s):
            return {'error': "server '{}' not accessible via salt".format(s)}
    gdm = GitDeployManager(gitdeploy, datasvc)
    res = gdm.deinitialize(server_list)
    existing_servers = gitdeploy['servers'] if 'servers' in gitdeploy else list()
    for s in server_list:
        if s in existing_servers:
            existing_servers.remove(s)
    datasvc.gitsvc.UpdateGitDeploy(gitdeploy['application'], gitdeploy['name'], {'servers': existing_servers})
    return res

def remove_and_deinitialize_gitdeploy(datasvc, gitdeploy):
    assert 'servers' in gitdeploy
    server_list = gitdeploy['servers']
    res1 = deinitialize_gitdeploy(datasvc, gitdeploy, server_list)
    res2 = remove_gitdeploy(datasvc, gitdeploy)
    return {
        'deinitialize': res1,
        'remove': res2
    }

def setup_local_gitrepo_dir(datasvc, gitrepo):
    logging.debug("setup_local_gitrepo: {}".format(gitrepo['name']))
    repo_service = BitBucketRepoService if gitrepo['gitprovider']['type'] == 'bitbucket' else GitHubRepoService
    rs = repo_service(gitrepo['gitprovider'], datasvc.settings)
    kp = gitrepo['keypair']
    rs.key_setup(gitrepo['name'], gitrepo['application'], kp)
    rs.setup_gitdeploy_dir(gitrepo['name'], gitrepo['application'], gitrepo['uri'], empty=False)

class GitRepoService:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, gitprovider, settings):
        self.gp_type = gitprovider['type']
        self.settings = settings
        self.auth = gitprovider['auth']
        self.base_url = BitBucketData.api_base_url if self.gp_type == 'bitbucket' else GitHubData.api_base_url

    def create_repo(self, name):
        logging.debug("create_repo not implemented")

    def get_alias(self, gitrepo_name, app):
        sshc = sshconfig.SSHController()
        return sshc.get_alias(gitrepo_name, app)

    def get_alias_uri(self, alias, original_uri):
        orig_domain = 'bitbucket.org' if self.gp_type == 'bitbucket' else 'github.com'
        return original_uri.replace(orig_domain, alias)

    def key_setup(self, gitrepo_name, application, keypair):
        '''
        copy keypair to user ssh dir
        add alias in ~/.ssh/config
        '''
        sshc = sshconfig.SSHController()
        alias_name = sshc.write_local_keys(application, self.gp_type, gitrepo_name, keypair['private_key'],
                                           keypair['public_key'])
        return alias_name

    def git_user_config(self, cwd):
        git = sh.git.bake(_cwd=cwd)
        hostname = socket.getfqdn()
        res = git.config("user.email", "elita@{}".format(hostname))
        logging.debug("setup_gitdeploy_dir: git config user.email: {}".format(res))
        res = git.config("user.name", "elita")
        logging.debug("setup_gitdeploy_dir: git config user.name: {}".format(res))
        res = git.config("--global", "push.default", "simple")
        logging.debug("setup_gitdeploy_dir: git config --global push.default simple: {}".format(res))

    def setup_gitdeploy_dir(self, gitrepo_name, application, uri, empty=False):
        '''create master gitdeploy directory and initialize with git'''
        logging.debug("setup_gitdeploy_dir: name: {}; app: {}; uri: {}".format(gitrepo_name, application, uri))
        root = self.settings['elita.gitdeploy.dir']
        if not os.path.isdir(root):
            os.mkdir(root)
        parent_path = os.path.join(root, application)
        if not os.path.isdir(parent_path):
            os.mkdir(parent_path)
        path = os.path.join(parent_path, gitrepo_name)
        alias = self.get_alias(gitrepo_name, application)
        alias_uri = self.get_alias_uri(alias , uri)
        if os.path.isdir(path) and empty:
            shutil.rmtree(path)
        if not os.path.isdir(path):
            os.mkdir(path)
            if empty:
                git = sh.git.bake(_cwd=path)
                res = git.init()
                logging.debug("setup_gitdeploy_dir: git init: {}".format(res))
                res = git.remote.add.origin("ssh://{}".format(alias_uri))
                logging.debug("setup_gitdeploy_dir: git remote add origin: {}".format(res))
                logging.debug("setup_gitdeploy_dir: creating initial repo with dummy file")
                touch = sh.touch.bake(_cwd=path)
                touch(".empty")
                res = git.add('-A')
                logging.debug("setup_gitdeploy_dir: git add: {}".format(res))
                self.git_user_config(path)
                res = git.commit(m="initial state")
                logging.debug("setup_gitdeploy_dir: git commit: {}".format(res))
                res = git.push("--set-upstream", "origin", "master")
                logging.debug("setup_gitdeploy_dir: git push: {}".format(res))
            else:
                git = sh.git.bake(_cwd=parent_path)
                logging.debug("setup_gitdeploy_dir: cloning repo")
                res = git.clone("ssh://{}".format(alias_uri), gitrepo_name)
                logging.debug("setup_gitdeploy_dir: res: {}".format(res))
                res = git.branch("--set-upstream-to=origin/master", "master")
                logging.debug("setup_gitdeploy_dir: git set upstream: {}".format(res))
                self.git_user_config(path)
        else:
            logging.debug("setup_gitdeploy_dir: local dir exists! not creating")

class GitHubRepoService(GitRepoService):
    __metaclass__ = elita.util.LoggingMetaClass
    pass

class BitBucketRepoService(GitRepoService):
    __metaclass__ = elita.util.LoggingMetaClass

    def create_repo(self, name):
        slug = slugify(name)
        username = self.auth['username']
        password = self.auth['password']
        json_body = {
            'scm': 'git',
            'name': name,
            'is_private': 'true',
            'description': "Created by elita",
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
        logging.debug("Deleting repo: {}".format(name))
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
        logging.debug("getting clone URI for {}".format(name))
        slug = slugify(name)
        username = self.auth['username']
        password = self.auth['password']
        r = requests.get("{}/repositories/{}/{}".format(self.base_url, username, slug), auth=(username, password))
        try:
            resp = r.json()
        except:
            logging.debug("exception parsing json resp!")
            return None
        for l in resp['links']['clone']:
            if l['name'] == "ssh":
                return l['href'][6:]  # chop off leading 'ssh://'
        logging.debug("nothing found in response!")
        return None

class GitDeployManager:
    __metaclass__ = elita.util.LoggingMetaClass
    
    def __init__(self, gitdeploy, datasvc):
        '''
        @type gitdeploy: dict
        @type datasvc: elita.models.DataService
        '''
        assert gitdeploy and datasvc
        assert elita.util.type_check.is_dictlike(gitdeploy)
        self.datasvc = datasvc
        self.gitdeploy = gitdeploy
        self.settings = datasvc.settings
        self.sc = salt_control.SaltController(datasvc)
        self.rc = salt_control.RemoteCommands(self.sc)

        if not os.path.isdir(self.get_path()):
            gitrepo = gitdeploy['location']['gitrepo']
            setup_local_gitrepo_dir(datasvc, gitrepo)

        #if there's no uri for associated gitrepo, try to fetch it
        if not gitdeploy['location']['gitrepo']['uri']:
            logging.debug("WARNING: found gitrepo with empty URI; fixing")
            repo_service = BitBucketRepoService if \
                gitdeploy['location']['gitrepo']['gitprovider']['type'] == "bitbucket" else GitHubRepoService
            rs = repo_service(gitdeploy['location']['gitrepo']['gitprovider'], self.settings)
            uri = rs.get_ssh_uri(gitdeploy['location']['gitrepo']['name'])
            assert uri is not None
            #need to get the original doc because of the dereferences
            git_repo = datasvc.gitsvc.GetGitRepo(gitdeploy['application'], gitdeploy['location']['gitrepo']['name'])
            datasvc.gitsvc.UpdateGitRepo(gitdeploy['application'], git_repo['name'], {'uri': uri})
            self.gitdeploy = datasvc.gitsvc.GetGitDeploy(gitdeploy['application'], gitdeploy['name'])

        if "last_build" in gitdeploy['location']['gitrepo']:
            self.last_build = gitdeploy['location']['gitrepo']['last_build']
        else:
            logging.debug("WARNING: found gitrepo without last_build")
            self.last_build = None

        self.deployed_build = gitdeploy['deployed_build']
        self.stale = False

    def update_stale(self):
        self.gitdeploy = self.datasvc.gitsvc.GetGitDeploy(self.gitdeploy['application'], self.gitdeploy['name'])
        self.last_build = self.gitdeploy['location']['gitrepo']['last_build']
        self.deployed_build = self.gitdeploy['deployed_build']
        self.stale = self.last_build != self.deployed_build

    def initialize(self, server_list):
        return {
            'prehook': self.run_init_prehook(server_list),
            'delete_remote_dir': self.delete_remote_dir(server_list),
            'create_remote_dir': self.create_remote_dir(server_list),
            'push_keys': self.push_keypair(server_list),
            'clone_repo': self.clone_repo(server_list),
            'create_gitignore': self.create_ignore(server_list),
            'posthook': self.run_init_posthook(server_list)
        }

    def deinitialize(self, server_list):
        return {
            'prehook': self.run_deinit_prehook(server_list),
            'delete_remote_dir': self.delete_remote_dir(server_list),
            'delete_remote_keys': self.delete_remote_keypair(server_list),
            'posthook': self.run_deinit_posthook(server_list)
        }

    def run_hook(self, hook, **kwargs):
        self.datasvc.jobsvc.NewJobData({'status': 'running hook {}'.format(hook)})
        args = {
            'hook_parameters':
                {
                    'gitdeploy': self.gitdeploy
                }
        }
        for k in kwargs:
            args['hook_parameters'][k] = kwargs[k]
        return self.datasvc.actionsvc.hooks.run_hook(self.gitdeploy['application'], hook, args)

    def run_init_prehook(self, server_list):
        return self.run_hook("GITDEPLOY_INIT_PRE", server_list=server_list)

    def run_init_posthook(self, server_list):
        return self.run_hook("GITDEPLOY_INIT_POST", server_list=server_list)

    def run_deinit_prehook(self, server_list):
        return self.run_hook("GITDEPLOY_DEINIT_PRE", server_list=server_list)

    def run_deinit_posthook(self, server_list):
        return self.run_hook("GITDEPLOY_DEINIT_POST", server_list=server_list)

    def run_commit_diffhook(self, files):
        return self.run_hook("GITDEPLOY_COMMIT_DIFF", files=files)

    def add_sls(self):
        self.sc.new_gitdeploy_yaml(self.gitdeploy)

    def rm_sls(self):
        self.sc.rm_gitdeploy_yaml(self.gitdeploy)

    def delete_remote_dir(self, server_list):
        logging.debug("delete_remote_dir")
        path = self.gitdeploy['location']['path']
        res = self.rc.delete_directory(server_list, path)
        logging.debug("delete_remote_dir on servers: {}: resp: {}".format(server_list, res))
        return res

    def create_remote_dir(self, server_list):
        logging.debug("create_remote_dir")
        path = self.gitdeploy['location']['path']
        res = self.rc.create_directory(server_list, path)
        logging.debug('create_remote_dir on servers: {}: resp: {}'.format(server_list, res))
        return res

    def delete_remote_keypair(self, server_list):
        return {'status': 'noop'}

    def push_keypair(self, server_list):
        '''
        Push the keypair to the target servers and set up SSH alias
        '''
        sshc = sshconfig.SSHController()
        return sshc.push_remote_keys(self.rc, server_list, self.gitdeploy['application'],
                                     self.gitdeploy['location']['gitrepo']['name'],
                                     self.gitdeploy['location']['gitrepo']['gitprovider']['type'],
                                     self.gitdeploy['location']['gitrepo']['keypair']['private_key'],
                                     self.gitdeploy['location']['gitrepo']['keypair']['public_key'])

    def clone_repo(self, server_list):
        logging.debug("clone_repo: cloning")
        sshc = sshconfig.SSHController()
        uri = sshc.get_full_alias_uri(self.gitdeploy['location']['gitrepo'])
        uri = "ssh://{}".format(uri)
        dest = self.gitdeploy['location']['path']
        res = self.rc.clone_repo(server_list, uri, dest)
        logging.debug("clone_repo: resp: {}".format(res))
        return res

    def create_ignore(self, server_list):
        repo_path = self.gitdeploy['location']['path']
        fd, temp_name = tempfile.mkstemp()
        logging.debug("create_ignore: writing file")
        if 'gitignore' in self.gitdeploy['options']:
            gi = self.gitdeploy['options']['gitignore']
            assert isinstance(gi, list)
            with open(temp_name, 'w') as f:
                for l in gi:
                    f.write("{}\n".format(l))
        logging.debug("create_ignore: pushing gitignore")
        remote_filename = os.path.join(repo_path, ".gitignore")
        res = self.rc.push_files(server_list, {temp_name: remote_filename})
        logging.debug("create_ignore: push resp: {}".format(res))
        logging.debug("create_ignore: autocrlf")
        res = self.rc.set_git_autocrlf(server_list, repo_path)
        logging.debug("create_ignore: autocrlf resp: {}".format(res))
        logging.debug("create_ignore: disabling push")
        res = self.rc.set_git_push_url(server_list, repo_path, "do.not.push")
        logging.debug("create_ignore: disable push resp: {}".format(res))
        logging.debug("create_ignore: adding file")
        res = self.rc.add_all_files_git(server_list, repo_path)
        logging.debug("create_ignore: add resp: {}".format(res))
        logging.debug("create_ignore: setting user config")
        res = self.rc.set_user_git(server_list, repo_path, "elita", "elita@elitaserver")
        logging.debug("create_ignore: config resp: {}".format(res))
        logging.debug("create_ignore: committing")
        res = self.rc.commit_git(server_list, repo_path, "gitignore")
        logging.debug("create_ignore: commit resp: {}".format(res))
        return res

    def get_path(self):
        appname = self.gitdeploy['application']
        gitrepo_name = self.gitdeploy['location']['gitrepo']['name']
        root = self.settings['elita.gitdeploy.dir']
        return "{}/{}/{}".format(root, appname, gitrepo_name)

    def git_obj(self):
        path = self.get_path()
        return sh.git.bake(_cwd=path)

    def get_latest_commit(self):
        repo = git.Repo(self.get_path())
        m = repo.heads.master
        return m.commit

    def get_latest_commit_hash(self):
        commit = self.get_latest_commit()
        return commit.hexsha

    def inspect_latest_diff(self):
        commit = self.get_latest_commit()
        logging.debug("commit hash: {}".format(commit.hexsha))
        s = commit.stats
        #replace all '.' with underscore to make Mongo happy
        #make copy for the hook
        return s.files    # not appropriate for direct inclusion into mongo due to filenames as keys

    def checkout_default_branch(self):
        branch = self.gitdeploy['location']['default_branch']
        logging.debug("checkout_default_branch: git checkout {}".format(branch))
        git = self.git_obj()
        return git.checkout(branch)

    def decompress_to_repo(self, package_doc):
        path = self.get_path()
        logging.debug("decompress_to_repo: deleting contents")
        for f in os.listdir(path):
            fpath = os.path.join(path, f)
            if os.path.isdir(fpath) and ".git" not in f:
                shutil.rmtree(fpath)
            elif os.path.isfile(fpath):
                os.unlink(fpath)
        logging.debug("decompress_to_repo: decompressing {} to {}".format(package_doc['filename'], path))
        bf = elita.builds.BuildFile(package_doc)
        bf.decompress(path)

    def check_repo_status(self):
        git = self.git_obj()
        return git.status()

    def add_files_to_repo(self):
        logging.debug("add_files_to_repo: git add")
        git = self.git_obj()
        return git.add('-A')

    def commit_to_repo(self, build_name):
        logging.debug("commit_to_repo: git commit")
        git = self.git_obj()
        return git.commit(m=build_name)

    def push_repo(self):
        logging.debug("push_repo: git push")
        git = self.git_obj()
        return git.push("-u", "origin", self.gitdeploy['location']['default_branch'])

    def update_repo_last_build(self, build_name):
        gitrepo_name = self.gitdeploy['location']['gitrepo']['name']
        logging.debug("update_repo_last_build: updating last_build on {} to {}".format(gitrepo_name, build_name))
        gitrepo = self.datasvc.gitsvc.GetGitRepo(self.gitdeploy['application'], gitrepo_name)
        gitrepo['last_build'] = build_name
        self.datasvc.gitsvc.UpdateGitRepo(self.gitdeploy['application'], gitrepo_name, gitrepo)
        self.update_stale()

    def update_last_deployed(self, build_name):
        self.datasvc.gitsvc.UpdateGitDeploy(self.gitdeploy['application'], self.gitdeploy['name'],
                                            {'deployed_build': build_name})
        self.update_stale()


