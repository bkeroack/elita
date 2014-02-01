import salt.client
import salt.config
import lockfile
import os
import os.path
import random
import shutil
import string
import simplejson as json
import yaml
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

import util
import gitservice

__author__ = 'bkeroack'

class FatalSaltError(Exception):
    pass

class OSTypes:
    Windows = 0
    Unix_like = 1

class RemoteCommands:
    def __init__(self, sc):
        self.sc = sc

    def get_os(self, server):
        resp = self.sc.salt_command(server, 'grains.item', ["os"])
        return OSTypes.Windows if resp[server]['os'] == "Windows" else OSTypes.Unix_like

    def create_directory(self, server_list, path):
        assert isinstance(server_list, list)
        return self.sc.salt_command(server_list, 'file.mkdir', [path])

    def delete_directory_win(self, server_list, path):
        return self.sc.salt_command(server_list, 'cmd.run', ["Remove-Item -Recurse -Force {}".format(path)],
                                    opts={'shell': 'powershell'})

    def delete_directory_unix(self, server_list, path):
        return self.sc.salt_command(server_list, 'cmd.run', ["rm -rf {}".format(path)])

    def delete_directory(self, server_list, path):
        assert isinstance(server_list, list)
        res = list()
        win_s = list()
        unix_s = list()
        for s in server_list:
            ost = self.get_os(s)
            if ost == OSTypes.Windows:
                win_s.append(s)
            elif os == OSTypes.Unix_like:
                unix_s.append(s)
        if len(win_s) > 0:
            res.append(self.delete_directory_win(win_s, path))
        if len(unix_s) > 0:
            res.append(self.delete_directory_unix(unix_s, path))
        return res

    def push_file(self, target, local_path, remote_path):
        r_postfix = ''.join(random.sample(string.letters + string.digits, 20))
        root = self.sc.sls_dir
        newname = os.path.basename(local_path) + r_postfix
        new_fullpath = "{}/{}".format(root, newname)
        shutil.copy(local_path, new_fullpath)
        salt_uri = 'salt://{}/{}'.format(self.sc.settings['daft.salt.slsdir'], newname)
        util.debugLog(self, "push_file: salt_uri: {}".format(salt_uri))
        util.debugLog(self, "push_file: remote_path: {}".format(remote_path))
        res = self.sc.salt_command(target, 'cp.get_file', [salt_uri, remote_path])
        util.debugLog(self, "push_file: resp: {}".format(res))
        os.unlink(new_fullpath)
        return {'success': {'target': target, 'remote_path': remote_path}}

    def push_key(self, server_list, file, name, ext):
        res = list()
        for s in server_list:
            ost = self.get_os(s)
            results = {
                'server': s,
                'os': ost,
                'results': []
            }
            if ost == OSTypes.Windows:
                path = 'C:\Program Files (x86)\Git\.ssh'
                fullpath = path + "\{}{}".format("id_rsa", ext)
            elif ost == OSTypes.Unix_like:
                path = '/etc/daft/keys'
                fullpath = path + '/{}{}'.format("id_rsa", ext)
            results['results'].append(self.create_directory([s], path))
            results['results'].append(self.push_file(s, file, fullpath))
            res.append(results)
        return res

    def clone_repo(self, server_list, repo_uri, dest):
        cwd, dest_dir = os.path.split(dest)
        return self.sc.salt_command(server_list, 'cmd.run',
                                    ['git clone {uri} {dest}'.format(uri=repo_uri, dest=dest_dir)],
                                    opts={'cwd': cwd}, timeout=1200)

    def checkout_branch(self, server_list, location, branch_name):
        return self.sc.salt_command(server_list, 'cmd.run', ['git checkout {}'.format(branch_name)],
                                    opts={'cwd': location})

    def highstate(self, server_list):
        return self.sc.salt_command(server_list, 'state.highstate', [], timeout=300)

class SaltController:
    def __init__(self, settings):
        self.settings = settings
        self.salt_client = salt.client.LocalClient()
        self.file_roots = None
        self.pillar_roots = None
        self.sls_dir = None

        self.load_salt_info()

    def salt_command(self, target, cmd, arg, opts={}, timeout=120):
        return self.salt_client.cmd(target, cmd, arg, kwarg=opts, timeout=timeout, expr_form='list')

    def run_command(self, target, cmd, shell, timeout=120):
        return self.salt_command(target, 'cmd.run', [cmd], opts={"shell": shell}, timeout=timeout)

    def load_salt_info(self):
        util.debugLog(self, "load_salt_info")
        master_config = salt.config.master_config(os.environ.get('SALT_MASTER_CONFIG', '/etc/salt/master'))
        self.file_roots = master_config['file_roots']
        for e in self.file_roots:
            for d in self.file_roots[e]:
                if not os.path.isdir(d):
                    os.mkdir(d)
        self.pillar_roots = master_config['pillar_roots']
        for e in self.pillar_roots:
            for d in self.pillar_roots[e]:
                if not os.path.isdir(d):
                    os.mkdir(d)
        self.sls_dir = "{}/{}".format(self.file_roots['base'][0], self.settings['daft.salt.slsdir'])
        if not os.path.isdir(self.sls_dir):
            os.mkdir(self.sls_dir)
        self.include_daft_top()

    def include_daft_top(self):
        util.debugLog(self, "include_daft_top")
        top_sls = "{}/top.sls".format(self.file_roots['base'][0])
        if not os.path.isfile(top_sls):
            util.debugLog(self, "WARNING: default salt top.sls not found! (check base file roots setting)")
            open(top_sls, 'a').close()
        lock = lockfile.FileLock(top_sls)
        lock.acquire(timeout=60)
        with open(top_sls, 'r') as f:
            top_content = yaml.load(f, Loader=Loader)
        write = False
        if top_content is None:
            util.debugLog(self, "include_daft_top: empty file")
            top_content = dict()
            write = True
        if 'include' not in top_content:
            util.debugLog(self, "include_daft_top: include not in top")
            top_content['include'] = dict()
            write = True
        if not isinstance(top_content['include'], list):
            util.debugLog(self, "include_daft_top: creating include list")
            top_content['include'] = list()
            write = True
        if 'daft' not in top_content['include']:
            util.debugLog(self, "include_daft_top: adding daft to include")
            top_content['include'].append('daft')
            write = True
        if write:
            util.debugLog(self, "include_daft_top: writing new top.sls")
            with open(top_sls, 'w') as f:
                f.write(yaml.safe_dump(top_content, default_flow_style=False))
        lock.release()

    def verify_connectivity(self, server, timeout=10):
        return len(self.salt_client.cmd(server, 'test.ping', timeout=timeout)) != 0

    def get_gd_file_name(self, app, name):
        if not os.path.isdir(self.sls_dir):
            os.mkdir(self.sls_dir)
        appdir = "{}/{}".format(self.sls_dir, app)
        if not os.path.isdir(appdir):
            os.mkdir(appdir)
        return "{}/{}.sls".format(appdir, name)

    def new_yaml(self, name, content):
        '''path must be relative to file_root'''
        new_file = self.get_gd_file_name(name)
        with open(new_file, 'w') as f:
            f.write(yaml.dump(content, Dumper=Dumper))

    def add_gitdeploy_servers_to_daft_top(self, server_list, app, gd_name):
        util.debugLog(self, "add_server_to_daft_top: server_list: {}".format(server_list))
        fname = "{}/{}".format(self.file_roots['base'][0], self.settings['daft.salt.dafttop'])
        if not os.path.isfile(fname):
            with open(fname, 'w') as f:
                f.write("\n")  # create if doesn't exist
        gdentry = "{}.{}.{}".format(self.settings['daft.salt.slsdir'], app, gd_name)
        util.debugLog(self, "add_server_to_daft_top: acquiring lock on {}".format(fname))
        lock = lockfile.FileLock(fname)
        lock.acquire(timeout=60)
        with open(fname, 'r') as f:
            dt_content = yaml.load(f, Loader=Loader)
        if not dt_content:
            dt_content = dict()
        if 'base' not in dt_content:
            dt_content['base'] = dict()
        for s in server_list:
            dt_content['base'][s] = [gdentry]
        with open(fname, 'w') as f:
            util.debugLog(self, "add_server_to_daft_top: writing file")
            f.write(yaml.safe_dump(dt_content, default_flow_style=False))
        lock.release()
        return "success"

    def new_gitdeploy_yaml(self, gitdeploy):
        '''Adds new gitdeploy to existing YAML file or creates new YAML file.'''
        name = gitdeploy['name']
        app = gitdeploy['application']
        filename = self.get_gd_file_name(app, name)
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
        favor = "theirs" if gitdeploy['options']['favor'] in ('theirs', 'remote') else 'ours'
        ignore_whitespace_op = "-Xignore-all-space" if gitdeploy['options']['ignore-whitespace'] == 'true' else ""
        dir = gitdeploy['location']['path']
        existing[slsname] = {
            'cmd.run': [
                {
                    'name': 'git pull -s recursive -X{favor} -Xpatience {ignorews}'
                    .format(favor=favor, ignorews=ignore_whitespace_op)
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
            util.change_dict_keys(prepull, gitservice.EMBEDDED_YAML_DOT_REPLACEMENT, '.')
            for k in prepull:
                top_key = prepull[k].keys()[0]
                prepull[k][top_key].append({'order': 0})
                existing[k] = prepull[k]
        postpull = gitdeploy['actions']['postpull']
        if postpull is not None:
            util.change_dict_keys(postpull, gitservice.EMBEDDED_YAML_DOT_REPLACEMENT, '.')
            for k in postpull:
                top_key = postpull[k].keys()[0]
                postpull[k][top_key].append({'order': 'last'})
                existing[k] = postpull[k]
        with open(filename, 'w') as f:
            f.write(yaml.safe_dump(existing, default_flow_style=False))
        lock.release()


