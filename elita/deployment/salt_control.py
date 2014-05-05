import salt.client
import salt.config
from salt.exceptions import SaltClientError
import lockfile
import os
import os.path
import random
import shutil
import string
import simplejson as json
import yaml
import elita.deployment.gitservice

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

import elita.util

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
        elita.util.debugLog(self, "get_os: resp: {}".format(resp))
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
        salt_uri = 'salt://{}/{}'.format(self.sc.settings['elita.salt.slsdir'], newname)
        elita.util.debugLog(self, "push_file: salt_uri: {}".format(salt_uri))
        elita.util.debugLog(self, "push_file: remote_path: {}".format(remote_path))
        res = self.sc.salt_command(target, 'cp.get_file', [salt_uri, remote_path])
        elita.util.debugLog(self, "push_file: resp: {}".format(res))
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
                path = '/etc/elita/keys'
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

    def discard_git_changes(self, server_list, location):
        return self.sc.salt_command(server_list, 'cmd.run', ['git checkout -f'],
                                    opts={'cwd': location})

    def add_all_files_git(self, server_list, location):
        return self.sc.salt_command(server_list, 'cmd.run', ['git add -A'], opts={'cwd': location}, timeout=120)

    def commit_git(self, server_list, location, message):
        return self.sc.salt_command(server_list, 'cmd.run', ['git commit -m "{}"'.format(message)],
                                    opts={'cwd': location}, timeout=120)

    def set_user_git(self, server_list, location, email, name):
        return {
            "name": self.sc.salt_command(server_list, 'cmd.run', ['git config user.name "{}"'.format(name)],
                                         opts={'cwd': location}, timeout=120),
            "email": self.sc.salt_command(server_list, 'cmd.run', ['git config user.email "{}"'.format(email)],
                                         opts={'cwd': location}, timeout=120)
        }

    def set_git_autocrlf(self, server_list, location):
        return self.sc.salt_command(server_list, 'cmd.run', ['git config core.autocrlf input'],
                                    opts={'cwd': location}, timeout=120)

    def set_git_push_url(self, server_list, location, url):
        return self.sc.salt_command(server_list, 'cmd.run', ['git remote set-url --push origin "{}"'.format(url)],
                                    opts={'cwd': location}, timeout=120)

    def highstate(self, server_list):
        return self.sc.salt_command(server_list, 'state.highstate', [], timeout=300)

    def run_sls(self, server_list, sls_name):
        return self.sc.salt_command(server_list, 'state.sls', [sls_name], timeout=300)

class SaltController:
    def __init__(self, settings):
        self.settings = settings
        self.salt_client = salt.client.LocalClient()
        self.file_roots = None
        self.pillar_roots = None
        self.sls_dir = None

        try:
            self.load_salt_info()
        except SaltClientError:
            elita.util.debugLog(self, "WARNING: SaltClientError")

    def salt_command(self, target, cmd, arg, opts=None, timeout=120):
        return self.salt_client.cmd(target, cmd, arg, kwarg=opts, timeout=timeout, expr_form='list')

    def run_command(self, target, cmd, shell, timeout=120):
        return self.salt_command(target, 'cmd.run', [cmd], opts={"shell": shell}, timeout=timeout)

    def load_salt_info(self):
        elita.util.debugLog(self, "load_salt_info")
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
        self.sls_dir = "{}/{}".format(self.file_roots['base'][0], self.settings['elita.salt.slsdir'])
        if not os.path.isdir(self.sls_dir):
            os.mkdir(self.sls_dir)
        #self.include_elita_top()

    # def include_elita_top(self):
    #     elita.util.debugLog(self, "include_elita_top")
    #     top_sls = "{}/top.sls".format(self.file_roots['base'][0])
    #     if not os.path.isfile(top_sls):
    #         elita.util.debugLog(self, "WARNING: default salt top.sls not found! (check base file roots setting)")
    #         open(top_sls, 'a').close()
    #     elita.util.debugLog(self, "acquiring lock on top.sls")
    #     lock = lockfile.FileLock(top_sls)
    #     lock.acquire(timeout=60)
    #     with open(top_sls, 'r') as f:
    #         top_content = yaml.load(f, Loader=Loader)
    #     write = False
    #     if top_content is None:
    #         elita.util.debugLog(self, "include_elita_top: empty file")
    #         top_content = dict()
    #         write = True
    #     if 'include' not in top_content:
    #         elita.util.debugLog(self, "include_elita_top: include not in top")
    #         top_content['include'] = dict()
    #         write = True
    #     if not isinstance(top_content['include'], list):
    #         elita.util.debugLog(self, "include_elita_top: creating include list")
    #         top_content['include'] = list()
    #         write = True
    #     if 'elita' not in top_content['include']:
    #         elita.util.debugLog(self, "include_elita_top: adding elita to include")
    #         top_content['include'].append('elita')
    #         write = True
    #     if write:
    #         elita.util.debugLog(self, "include_elita_top: writing new top.sls")
    #         with open(top_sls, 'w') as f:
    #             f.write(yaml.safe_dump(top_content, default_flow_style=False))
    #     lock.release()

    def verify_connectivity(self, server, timeout=10):
        return len(self.salt_client.cmd(server, 'test.ping', timeout=timeout)) != 0

    def get_gd_file_name(self, app, name):
        if not os.path.isdir(self.sls_dir):
            os.mkdir(self.sls_dir)
        appdir = "{}/{}".format(self.sls_dir, app)
        if not os.path.isdir(appdir):
            os.mkdir(appdir)
        return "{}/{}.sls".format(appdir, name)

    # def get_elita_top_filename(self):
    #     return "{}/{}".format(self.file_roots['base'][0], self.settings['elita.salt.elitatop'])

    def get_gitdeploy_entry_name(self, app, gd_name):
         return "{}.{}.{}".format(self.settings['elita.salt.slsdir'], app, gd_name)

    # def add_gitdeploy_servers_to_elita_top(self, server_list, app, gd_name):
    #     elita.util.debugLog(self, "add_server_to_elita_top: server_list: {}".format(server_list))
    #     fname = self.get_elita_top_filename()
    #     if not os.path.isfile(fname):
    #         with open(fname, 'w') as f:
    #             f.write("\n")  # create if doesn't exist
    #     gdentry = self.get_gitdeploy_entry_name(app, gd_name)
    #     elita.util.debugLog(self, "add_server_to_elita_top: acquiring lock on {}".format(fname))
    #     lock = lockfile.FileLock(fname)
    #     lock.acquire(timeout=60)
    #     with open(fname, 'r') as f:
    #         dt_content = yaml.load(f, Loader=Loader)
    #     if not dt_content:
    #         dt_content = dict()
    #     if 'base' not in dt_content or not dt_content['base']:
    #         dt_content['base'] = dict()
    #     for s in server_list:
    #         if s not in dt_content['base']:
    #             dt_content['base'][s] = list()
    #         gdset = set(tuple(dt_content['base'][s]))
    #         gdset.add(gdentry)
    #         dt_content['base'][s] = list(gdset)
    #     with open(fname, 'w') as f:
    #         elita.util.debugLog(self, "add_server_to_elita_top: writing file")
    #         f.write(yaml.safe_dump(dt_content, default_flow_style=False))
    #     lock.release()
    #     return "success"

    # def rm_gitdeploy_servers_from_elita_top(self, server_list, app, gd_name):
    #     elita.util.debugLog(self, "rm_server_from_elita_top: server_list: {}".format(server_list))
    #     elita_top = self.get_elita_top_filename()
    #     assert os.path.isfile(elita_top)
    #     elita.util.debugLog(self, "rm_server_from_elita_top: acquiring lock on {}".format(elita_top))
    #     lock = lockfile.FileLock(elita_top)
    #     lock.acquire(timeout=60)
    #     with open(elita_top, 'r') as f:
    #         dt_content = yaml.load(f, Loader=Loader)
    #     assert dt_content
    #     assert 'base' in dt_content
    #     for s in server_list:
    #         if s in dt_content['base']:
    #             if "elita.{}.{}".format(app, gd_name) in dt_content['base'][s]:
    #                 elita.util.debugLog(self, "rm_server_from_elita_top: deleting gitdeploy {} from server {} in elita top".
    #                               format(gd_name, s))
    #                 del dt_content['base'][s]
    #             else:
    #                 elita.util.debugLog(self, "rm_server_from_elita_top: WARNING: gitdeploy {} not found in elita top".
    #                               format(gd_name))
    #         else:
    #             elita.util.debugLog(self, "rm_server_from_elita_top: WARNING: server {} not found in elita top".format(s))
    #     with open(elita_top, 'w') as f:
    #         elita.util.debugLog(self, "rm_server_from_elita_top: writing file")
    #         f.write(yaml.safe_dump(dt_content, default_flow_style=False))
    #     lock.release()
    #     return "success"

    def rm_gitdeploy_yaml(self, gitdeploy):
        name = gitdeploy['name']
        app = gitdeploy['application']
        filename = self.get_gd_file_name(app, name)
        elita.util.debugLog(self, "rm_gitdeploy_yaml: gitdeploy: {}/{}".format(app, name))
        elita.util.debugLog(self, "rm_gitdeploy_yaml: filename: {}".format(filename))
        if not os.path.isfile(filename):
            elita.util.debugLog(self, "rm_gitdeploy_yaml: WARNING: file not found!")
            return
        lock = lockfile.FileLock(filename)
        elita.util.debugLog(self, "rm_gitdeploy_yaml: acquiring lock on {}".format(filename))
        lock.acquire(timeout=60)
        os.unlink(filename)
        lock.release()

    def new_gitdeploy_yaml(self, gitdeploy):
        '''Adds new gitdeploy to existing YAML file or creates new YAML file.'''
        name = gitdeploy['name']
        app = gitdeploy['application']
        filename = self.get_gd_file_name(app, name)
        elita.util.debugLog(self, "add_gitdeploy_to_yaml: acquiring lock on {}".format(filename))
        lock = lockfile.FileLock(filename)
        lock.acquire(timeout=60)  # throws exception if timeout
        if os.path.isfile(filename):
            elita.util.debugLog(self, "add_gitdeploy_to_yaml: existing yaml sls")
            with open(filename, 'r') as f:
                existing = yaml.load(f, Loader=Loader)
        else:
            elita.util.debugLog(self, "add_gitdeploy_to_yaml: yaml sls does not exist")
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
            elita.util.change_dict_keys(prepull, elita.deployment.gitservice.EMBEDDED_YAML_DOT_REPLACEMENT, '.')
            for k in prepull:
                top_key = prepull[k].keys()[0]
                prepull[k][top_key].append({'order': 0})
                existing[k] = prepull[k]
        postpull = gitdeploy['actions']['postpull']
        if postpull is not None:
            elita.util.change_dict_keys(postpull, elita.deployment.gitservice.EMBEDDED_YAML_DOT_REPLACEMENT, '.')
            for k in postpull:
                top_key = postpull[k].keys()[0]
                postpull[k][top_key].append({'order': 'last'})
                existing[k] = postpull[k]
        with open(filename, 'w') as f:
            f.write(yaml.safe_dump(existing, default_flow_style=False))
        lock.release()


