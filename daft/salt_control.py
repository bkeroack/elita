import salt.client
import lockfile
import os.path
import random
import shutil
import string
import yaml
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

import util

__author__ = 'bkeroack'

class OSTypes:
    Windows = 0
    Unix_like = 1

class RemoteCommands:
    def __init__(self, sc):
        self.sc = sc

    def get_os(self, server):
        resp = self.sc.salt_command(server, 'grains.item', opts={'arg': ["os"]})
        return OSTypes.Windows if resp[server]['os'] == "Windows" else OSTypes.Unix_like

    def create_directory(self, server, path):
        return self.sc.salt_command(server, 'file.makedirs', opts={'arg': [path]})

    def push_file(self, target, local_path, remote_path):
        r_postfix = ''.join(random.sample(string.letters + string.digits, 20))
        root = self.sc.file_roots['base'][0]
        newname = os.path.basename(local_path) + r_postfix
        new_fullpath = "{}/{}".format(root, newname)
        shutil.copy(local_path, new_fullpath)
        salt_uri = 'salt://{}'.format(newname)
        res = self.sc.salt_command(target, 'cp.get_file', opts={
            'arg': [salt_uri, remote_path]
        })
        util.debugLog(self, "push_file: resp: {}".format(res))
        os.unlink(new_fullpath)

    def push_key(self, server, file, name, ext):
        ost = self.get_os(server)
        if ost == OSTypes.Windows:
            return self.push_file(server, file, 'C:\\Program Files (x86)\\Git\\.ssh\\{}.pub'.format(name))
        elif ost == OSTypes.Unix_like:
            return self.push_file(server, file, '/etc/daft/keys/{}{}'.format(name, ext))
        else:
            assert False

    def clone_repo(self, server, repo_uri, dest):
        cwd, dest_dir = os.path.split(dest)
        return self.sc.salt_command(server, 'cmd.run', opts={
            'arg': ['git clone {uri} {dest}'.format(repo_uri, dest_dir)],
            'cwd': cwd
        }, timeout=1200)

class SaltController:
    def __init__(self, settings):
        self.settings = settings
        self.salt_client = salt.client.LocalClient()
        self.file_roots = None
        self.pillar_roots = None
        self.load_salt_info()

    def salt_command(self, target, cmd, opts={}, timeout=120):
        opts['timeout'] = timeout
        return self.salt_client.cmd(target, cmd, **opts)

    def run_command(self, target, cmd, shell, timeout=120):
        return self.salt_command(target, 'cmd.run', {"arg": [cmd], "shell": shell}, timeout=timeout)

    def load_salt_info(self):
        util.debugLog(self, "load_salt_info: self.settings: {}".format(self.settings))
        with open(self.settings['daft.salt.config'], 'r') as f:
            salt_config = yaml.load(f, Loader=Loader)
            util.debugLog(self, "load_salt_info: salt_config: {}".format(salt_config))
            self.file_roots = salt_config['file_roots'] if 'file_roots' in salt_config else {'base': ['/srv/salt']}
            self.pillar_roots = salt_config['pillar_roots'] if 'pillar_roots' in salt_config else {'base': ['/srv/pillar']}

    def verify_connectivity(self, server, timeout=10):
        return len(self.salt_client.cmd(server, 'test.ping', timeout=timeout)) != 0

    def get_file_name(self, name):
        root = self.file_roots['base'][0]
        path = self.settings['daft.salt.dir']
        return "{}/{}/{}.sls".format(root, path, name)

    def new_yaml(self, name, content):
        '''path must be relative to file_root'''
        new_file = self.get_file_name(name)
        with open(new_file, 'w') as f:
            f.write(yaml.dump(content, Dumper=Dumper))

    def add_gitdeploy_to_yaml(self, gitdeploy):
        '''Adds new gitdeploy to existing YAML file. Top-level keys in content will clobber existing ones in the file'''
        name = gitdeploy['name']
        filename = self.get_file_name(name)
        util.debugLog(self, "add_gitdeploy_to_yaml: filename: {}".format(filename))
        lock = lockfile.FileLock(filename)
        lock.acquire(timeout=60)  # throws exception if timeout
        if os.path.isfile(filename):
            util.debugLog(self, "add_gitdeploy_to_yaml: existing yaml sls")
            with open(filename, 'r') as f:
                existing = yaml.load(f, Loader=Loader)
        else:
            util.debugLog(self, "add_gitdeploy_to_yaml: yaml sls does not exist")
            existing = dict()
        slsname = 'gitdeploy_{}'.format(name)
        branch = gitdeploy['location']['default_branch']
        favor = "theirs" if gitdeploy['options']['favor'] in ('theirs', 'remote') else 'ours'
        ignore_whitespace_op = "-Xignore-all-space" if gitdeploy['options']['ignore-whitespace'] == 'true' else ""
        dir = gitdeploy['location']['path']
        existing[slsname] = {
            'cmd.run': [
                {
                    'name': 'git checkout {branch} && git fetch && git merge -s recursive -X{favor} -Xpatience {ignorews}'
                    .format(branch=branch, favor=favor, ignorews=ignore_whitespace_op)
                },
                {
                    'cwd': dir
                },
                {
                    'failhard': 'true'
                },
                {
                    'order': 1
                }
            ]
        }
        prepull = gitdeploy['actions']['prepull']
        if prepull is not None:
            for k in prepull:
                top_key = prepull[k].keys()[0]
                prepull[k][top_key].append({'order': 0})
                existing[k] = prepull[k]
        postpull = gitdeploy['actions']['postpull']
        if postpull is not None:
            for k in postpull:
                top_key = postpull[k].keys()[0]
                postpull[k][top_key].append({'order': 'last'})
                existing[k] = postpull[k]
        with open(filename, 'w') as f:
            f.write(yaml.dump(existing, Dumper=Dumper, default_flow_style=False))
        lock.release()


