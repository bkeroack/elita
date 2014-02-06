import requests
from slugify import slugify
import tempfile
import os
import shutil
import stat
import sh
import lockfile

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

#mongo does not allow dots in key names, so we have to replace dots in embedded yaml dict keys with this
EMBEDDED_YAML_DOT_REPLACEMENT = '#'

#callables for async execution
def create_bitbucket_repo(datasvc, gitprovider, name, application, keypair):
    bbsvc = BitBucketRepoService(gitprovider, datasvc.settings)
    resp = bbsvc.create_repo(name)
    uri = bbsvc.get_ssh_uri(name)
    if uri:
        util.debugLog(create_bitbucket_repo, "got uri: {}".format(uri))
        alias = bbsvc.key_setup(name, application, keypair)
        alias_uri = uri.replace("bitbucket.org", alias)
        util.debugLog(create_bitbucket_repo, "alias uri: {}".format(alias_uri))
        bbsvc.setup_gitdeploy_dir(name, application, alias_uri)
        datasvc.gitsvc.UpdateGitRepo(application, name, {'uri': uri})
    else:
        util.debugLog(create_bitbucket_repo, "ERROR: uri for gitrepo not found!")
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

def initialize_gitdeploy(datasvc, gitdeploy, server_list):
    sc = salt_control.SaltController(datasvc.settings)
    for s in server_list:
        if not sc.verify_connectivity(s):
            return {'error': "server '{}' not accessible via salt".format(s)}
    gdm = GitDeployManager(gitdeploy, datasvc)
    return gdm.initialize(server_list)

class GitRepoService:
    def __init__(self, gitprovider, settings):
        self.gp_type = gitprovider['type']
        self.settings = settings
        self.auth = gitprovider['auth']
        self.base_url = BitBucketData.api_base_url if self.gp_type == 'bitbucket' else GitHubData.api_base_url

    def create_repo(self, name):
        util.debugLog(self, "create_repo not implemented")

    def key_setup(self, name, application, keypair):
        #copy keypair to user ssh dir
        #add alias in ~/.ssh/config
        home_dir = os.path.expanduser('~')
        priv_key_name = "{}/.ssh/{}-{}".format(home_dir, application, name)
        pub_key_name = "{}.pub".format(priv_key_name)

        util.debugLog(self, "key_setup: home_dir: {}".format(home_dir))
        util.debugLog(self, "key_setup: priv_key_name: {}".format(priv_key_name))
        util.debugLog(self, "key_setup: pub_key_name: {}".format(pub_key_name))


        util.debugLog(self, "key_setup: writing keypairs")
        with open(pub_key_name, 'w') as f:
            f.write(keypair['public_key'].decode('string_escape'))

        with open(priv_key_name, 'w') as f:
            f.write(keypair['private_key'].decode('string_escape'))

        util.debugLog(self, "key_setup: chmod private key to owner read/write only")
        os.chmod(priv_key_name, stat.S_IWUSR | stat.S_IRUSR)

        util.debugLog(self, "key_setup: adding alias to ssh config")
        ssh_config = "{}/.ssh/config".format(home_dir)
        alias_name = "{}-{}".format(application, name)
        lock = lockfile.FileLock(ssh_config)
        lock.acquire(timeout=60)
        with open(ssh_config, 'a') as f:
            f.write("\nHost {}\n".format(alias_name))
            f.write("\tHostName {}\n".format("bitbucket.org" if self.gp_type == 'bitbucket' else "github.com"))
            f.write("\tPreferredAuthentications publickey\n")
            f.write("\tStrictHostKeyChecking no\n")
            f.write("\tIdentityFile {}\n".format(priv_key_name))
        os.chmod(ssh_config, stat.S_IWUSR | stat.S_IRUSR)
        lock.release()
        return alias_name

    def setup_gitdeploy_dir(self, name, application, uri):
        '''create master gitdeploy directory and initialize with git'''
        util.debugLog(self, "setup_gitdeploy_dir: name: {}; app: {}; uri: {}".format(name, application, uri))
        root = self.settings['daft.gitdeploy.dir']
        if not os.path.isdir(root):
            os.mkdir(root)
        path = "{}/{}".format(root, application)
        if not os.path.isdir(path):
            os.mkdir(path)
        path += "/{}".format(name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        os.mkdir(path)
        git = sh.git.bake(_cwd=path)
        res = git.init()
        util.debugLog(self, "setup_gitdeploy_dir: git init: {}".format(res))
        res = git.remote.add.origin("ssh://{}".format(uri))
        util.debugLog(self, "setup_gitdeploy_dir: git remote add origin: {}".format(res))
        util.debugLog(self, "setup_gitdeploy_dir: creating initial repo with dummy file")
        touch = sh.touch.bake(_cwd=path)
        touch(".empty")
        res = git.add('-A')
        util.debugLog(self, "setup_gitdeploy_dir: git add: {}".format(res))
        res = git.config("user.email", "daft@locahost")
        util.debugLog(self, "setup_gitdeploy_dir: git config user.email: {}".format(res))
        res = git.config("user.name", "daft")
        util.debugLog(self, "setup_gitdeploy_dir: git config user.name: {}".format(res))
        res = git.config("--global", "push.default", "simple")
        util.debugLog(self, "setup_gitdeploy_dir: git config --global push.default simple: {}".format(res))
        res = git.commit(m="initial state")
        util.debugLog(self, "setup_gitdeploy_dir: git commit: {}".format(res))
        res = git.push("--set-upstream", "origin", "master")
        util.debugLog(self, "setup_gitdeploy_dir: git push: {}".format(res))

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
            util.debugLog(self, "exception parsing json resp!")
            return None
        for l in resp['links']['clone']:
            if l['name'] == "ssh":
                return l['href'][6:]  # chop off leading 'ssh://'
        util.debugLog(self, "nothing found in response!")
        return None

class GitDeployManager:
    def __init__(self, gitdeploy, datasvc):
        self.datasvc = datasvc
        self.gitdeploy = gitdeploy
        self.settings = datasvc.settings
        self.sc = salt_control.SaltController(self.settings)
        self.rc = salt_control.RemoteCommands(self.sc)

    def initialize(self, server_list):
        return {
            'prehook': self.run_init_prehook(server_list),
            'delete_remote_dir': self.delete_remote_dir(server_list),
            'create_remote_dir': self.create_remote_dir(server_list),
            'push_keys': self.push_keypair(server_list),
            'add_to_top': self.add_to_top(server_list),
            'clone_repo': self.clone_repo(server_list),
            'create_gitignore': self.create_ignore(server_list),
            'posthook': self.run_init_posthook(server_list)
        }

    def run_hook(self, hook, server_list):
        self.datasvc.jobsvc.NewJobData({'status': 'running hook {}'.format(hook)})
        args = {
            'hook_parameters':
                {
                    'gitdeploy': self.gitdeploy,
                    'server_list': server_list
                }
        }
        return self.datasvc.actionsvc.hooks.run_hook(self.gitdeploy['application'], hook, args)

    def run_init_prehook(self, server_list):
        return self.run_hook("GITDEPLOY_INIT_PRE", server_list)

    def run_init_posthook(self, server_list):
        return self.run_hook("GITDEPLOY_INIT_POST", server_list)

    def add_sls(self):
        self.sc.new_gitdeploy_yaml(self.gitdeploy)

    def add_to_top(self, server_list):
        return self.sc.add_gitdeploy_servers_to_daft_top(server_list, self.gitdeploy['application'],
                                                         self.gitdeploy['name'])

    def delete_remote_dir(self, server_list):
        util.debugLog(self, "delete_remote_dir")
        path = self.gitdeploy['location']['path']
        res = self.rc.delete_directory(server_list, path)
        util.debugLog(self, "delete_remote_dir on servers: {}: resp: {}".format(server_list, res))
        return res

    def create_remote_dir(self, server_list):
        util.debugLog(self, "create_remote_dir")
        path = self.gitdeploy['location']['path']
        res = self.rc.create_directory(server_list, path)
        util.debugLog(self, 'create_remote_dir on servers: {}: resp: {}'.format(server_list, res))
        return res

    def push_keypair(self, server_list):
        f_pub, tf_pub = tempfile.mkstemp(text=True)
        with open(tf_pub, 'w') as f:
            f.write(self.gitdeploy['location']['gitrepo']['keypair']['public_key'].decode('string_escape'))

        f_priv, tf_priv = tempfile.mkstemp(text=True)
        with open(tf_priv, 'w') as f:
            f.write(self.gitdeploy['location']['gitrepo']['keypair']['private_key'].decode('string_escape'))

        res_pub = self.rc.push_key(server_list, tf_pub, self.gitdeploy['name'], '.pub')
        util.debugLog(self, "push_keypair: push pub resp: {}".format(res_pub))
        res_priv = self.rc.push_key(server_list, tf_priv, self.gitdeploy['name'], '')
        util.debugLog(self, "push_keypair: push priv resp: {}".format(res_priv))
        os.unlink(tf_pub)
        os.unlink(tf_priv)
        return res_pub, res_priv

    def clone_repo(self, server_list):
        util.debugLog(self, "clone_repo: cloning")
        uri = "ssh://{}".format(self.gitdeploy['location']['gitrepo']['uri'])
        dest = self.gitdeploy['location']['path']
        res = self.rc.clone_repo(server_list, uri, dest)
        util.debugLog(self, "clone_repo: resp: {}".format(res))
        return res

    def create_ignore(self, server_list):
        repo_path = self.gitdeploy['location']['path']
        fd, temp_name = tempfile.mkstemp()
        util.debugLog(self, "create_ignore: writing file")
        if 'gitignore' in self.gitdeploy['options']:
            gi = self.gitdeploy['options']['gitignore']
            assert isinstance(gi, list)
            with open(temp_name, 'w') as f:
                for l in gi:
                    f.write("{}\n".format(l))
        util.debugLog(self, "create_ignore: pushing gitignore")
        remote_filename = os.path.join(repo_path, ".gitignore")
        res = self.rc.push_file(server_list, temp_name, remote_filename)
        util.debugLog(self, "create_ignore: push resp: {}".format(res))
        util.debugLog(self, "create_ignore: autocrlf")
        res = self.rc.set_git_autocrlf(server_list, repo_path)
        util.debugLog(self, "create_ignore: autocrlf resp: {}".format(res))
        util.debugLog(self, "create_ignore: disabling push")
        res = self.rc.set_git_push_url(server_list, repo_path, "do.not.push")
        util.debugLog(self, "create_ignore: disable push resp: {}".format(res))
        util.debugLog(self, "create_ignore: adding file")
        res = self.rc.add_all_files_git(server_list, repo_path)
        util.debugLog(self, "create_ignore: add resp: {}".format(res))
        util.debugLog(self, "create_ignore: setting user config")
        res = self.rc.set_user_git(server_list, repo_path, "daft", "daft@daftserver")
        util.debugLog(self, "create_ignore: config resp: {}".format(res))
        util.debugLog(self, "create_ignore: committing")
        res = self.rc.commit_git(server_list, repo_path, "gitignore")
        util.debugLog(self, "create_ignore: commit resp: {}".format(res))
        return res

    def get_path(self):
        appname = self.gitdeploy['application']
        gitrepo_name = self.gitdeploy['location']['gitrepo']['name']
        root = self.settings['daft.gitdeploy.dir']
        return "{}/{}/{}".format(root, appname, gitrepo_name)

    def git_obj(self):
        path = self.get_path()
        return sh.git.bake(_cwd=path)

    def checkout_default_branch(self):
        branch = self.gitdeploy['location']['default_branch']
        util.debugLog(self, "checkout_default_branch: git checkout {}".format(branch))
        git = self.git_obj()
        return git.checkout(branch)

    def decompress_to_repo(self, package_doc):
        path = self.get_path()
        util.debugLog(self, "decompress_to_repo: deleting contents")
        for f in os.listdir(path):
            fpath = os.path.join(path, f)
            if os.path.isdir(fpath) and ".git" not in f:
                shutil.rmtree(fpath)
            elif os.path.isfile(fpath):
                os.unlink(fpath)
        util.debugLog(self, "decompress_to_repo: decompressing {} to {}".format(package_doc['filename'], path))
        bf = builds.BuildFile(package_doc)
        bf.decompress(path)

    def check_repo_status(self):
        git = self.git_obj()
        return git.status()

    def add_files_to_repo(self):
        util.debugLog(self, "add_files_to_repo: git add")
        git = self.git_obj()
        return git.add('-A')

    def commit_to_repo(self, build_name):
        util.debugLog(self, "commit_to_repo: git commit")
        git = self.git_obj()
        return git.commit(m=build_name)

    def push_repo(self):
        util.debugLog(self, "push_repo: git push")
        git = self.git_obj()
        return git.push()




