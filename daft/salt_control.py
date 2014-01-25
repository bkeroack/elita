import salt.client
import salt.config
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

    def create_directory(self, server_list, path):
        assert isinstance(server_list, list)
        return self.sc.salt_command(server_list, 'file.makedirs', opts={'expr_form': 'list', 'arg': [path]})

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

    def push_key(self, server_list, file, name, ext):
        res = list()
        for s in server_list:
            ost = self.get_os(s)
            if ost == OSTypes.Windows:
                res.append(self.push_file(s, file, 'C:\\Program Files (x86)\\Git\\.ssh\\{}.pub'.format(name)))
            elif ost == OSTypes.Unix_like:
                res.append(self.push_file(s, file, '/etc/daft/keys/{}{}'.format(name, ext)))
            else:
                assert False
        return res

    def clone_repo(self, server_list, repo_uri, dest):
        cwd, dest_dir = os.path.split(dest)
        return self.sc.salt_command(server_list, 'cmd.run', opts={
            'arg': ['git clone {uri} {dest}'.format(repo_uri, dest_dir)],
            'cwd': cwd,
            'expr_form': list
        }, timeout=1200)

    def highstate(self, server_list):
        return self.sc.salt_command(server_list, 'state.highstate', opts={'expr_form': 'list'}, timeout=300)

class SaltController:
    def __init__(self, settings):
        self.settings = settings
        self.salt_client = salt.client.LocalClient()
        self.file_roots = None
        self.pillar_roots = None
        self.sls_dir = None

        self.load_salt_info()

    def salt_command(self, target, cmd, opts={}, timeout=120):
        opts['timeout'] = timeout
        return self.salt_client.cmd(target, cmd, **opts)

    def run_command(self, target, cmd, shell, timeout=120):
        return self.salt_command(target, 'cmd.run', {"arg": [cmd], "shell": shell}, timeout=timeout)

    def load_salt_info(self):
        util.debugLog(self, "load_salt_info")
        master_config = salt.config.master_config(os.environ.get('SALT_MASTER_CONFIG', '/etc/salt/master'))
        self.file_roots = master_config['file_roots']
        self.pillar_roots = master_config['pillar_roots']
        self.sls_dir = "{}/{}".format(self.file_roots['base'][0], self.settings['daft.salt.slsdir'])
        if not os.path.isdir(self.sls_dir):
            os.mkdir(self.sls_dir)

    def verify_connectivity(self, server, timeout=10):
        return len(self.salt_client.cmd(server, 'test.ping', timeout=timeout)) != 0

    def get_gd_file_name(self, name):
        path = self.sls_dir
        return "{}/{}.sls".format(path, name)

    def new_yaml(self, name, content):
        '''path must be relative to file_root'''
        new_file = self.get_gd_file_name(name)
        with open(new_file, 'w') as f:
            f.write(yaml.dump(content, Dumper=Dumper))

    def add_servers_to_daft_top(self, server_list):
        util.debugLog(self, "add_server_to_daft_top: server_list: {}".format(server_list))
        fname = "{}/{}".format(self.file_roots['base'][0], self.settings['daft.salt.dafttop'])
        util.debugLog(self, "add_server_to_daft_top: acquiring lock on {}".format(fname))
        lock = lockfile.FileLock(fname)
        lock.acquire(timeout=60)
        with open(fname, 'r') as f:
            dt_content = yaml.load(f, Loader=Loader)
        for s in server_list:
            dt_content['base'][s] = ['none']
        with open(fname, 'w') as f:
            f.write(yaml.dump(dt_content, Dumper=Dumper))
        lock.release()

    def new_gitdeploy_yaml(self, gitdeploy):
        '''Adds new gitdeploy to existing YAML file or creates new YAML file.'''
        name = gitdeploy['name']
        filename = self.get_gd_file_name(name)
        util.debugLog(self, "add_gitdeploy_to_yaml: acquiring lock on {}".format(filename))
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
                    'name': 'git checkout {branch}; git pull -s recursive -X{favor} -Xpatience {ignorews}'
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


