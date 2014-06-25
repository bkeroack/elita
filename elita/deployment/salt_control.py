import salt.client
import salt.config
from salt.exceptions import SaltClientError
import lockfile
import os
import os.path
import random
import shutil
import string
import yaml
import logging
import elita.deployment.gitservice

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

import elita.util

__author__ = 'bkeroack'

WINDOWS_KEY_LOCATION = 'C:\Program Files (x86)\Git\.ssh'
UNIX_KEY_LOCATION = '~/.ssh'
UNIX_MINION_USER = 'root'  # hack

class FatalSaltError(Exception):
    pass

class OSTypes:
    Windows = 0
    Unix_like = 1

class RemoteCommands:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, sc):
        self.sc = sc

    def get_os(self, server):
        resp = self.sc.salt_command(server, 'grains.item', ["os"])
        logging.debug("get_os: resp: {}".format(resp))
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
        logging.debug("push_file: salt_uri: {}".format(salt_uri))
        logging.debug("push_file: remote_path: {}".format(remote_path))
        res = self.sc.salt_command(target, 'cp.get_file', [salt_uri, remote_path])
        logging.debug("push_file: resp: {}".format(res))
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
            # on Windows, salt-minion runs as LOCALSYSTEM which does not have a home directory
            # therefore we have to create a place to put keys
            if ost == OSTypes.Windows:
                path = WINDOWS_KEY_LOCATION
                fullpath = path + "\\{}{}".format("id_rsa", ext)
            elif ost == OSTypes.Unix_like:
                path = UNIX_KEY_LOCATION
                fullpath = os.path.join(path, "id_rsa{}".format(ext))
            results['results'].append(self.create_directory([s], path))
            results['results'].append(self.push_file(s, file, fullpath))
            res.append(results)
        return res

    def add_ssh_alias(self, server_list, alias_name, real_hostname, keyname):
        '''
        Append alias to ssh config
        '''
        win_servers = list()
        unix_servers = list()
        for s in server_list:
            ost = self.get_os(s)
            if ost == OSTypes.Windows:
                win_servers.append(s)
            elif ost == OSTypes.Unix_like:
                unix_servers.append(s)
        unix_sshconfig = os.path.join(UNIX_KEY_LOCATION, "config")
        win_sshconfig = "{}\\{}".format(WINDOWS_KEY_LOCATION, "config")
        alias = """
Host {alias}
\tHostname {hostname}
\tIdentityFile {keyfile}
\t
asdf
""".format()
        return {
            'unix_servers': self.sc.salt_command(unix_servers,
                                                 ['file.mkdir',
                                                  'file.touch',
                                                  'file.append',
                                                  'file.check_perms'],
                                                 [
                                                     [UNIX_KEY_LOCATION],
                                                     [unix_sshconfig],
                                                     [unix_sshconfig, alias],
                                                     [unix_sshconfig, '{}', UNIX_MINION_USER, UNIX_MINION_USER, '600']
                                                 ]),
            'windows_servers': self.sc.salt_command(win_servers,
                                                    ['file.mkdir',
                                                    'file.touch',
                                                    'file.append'],
                                                    [
                                                        [WINDOWS_KEY_LOCATION],
                                                        [win_sshconfig],
                                                        [win_sshconfig, alias]
                                                    ])
        }


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

    def run_slses_async(self, callback, sls_map, args=None):
        '''
        sls_map: { 'sls_name': [ list_of_servers ] }
        Runs all listed SLSes asynchronously
        '''
        cmd_group = [{'command': 'state.sls', 'arguments': [s], 'servers': sls_map[s]} for s in sls_map]
        return self.sc.salt_commands_async(callback, args, cmd_group, timeout=300)

class SaltController:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, settings):
        self.settings = settings
        self.salt_client = salt.client.LocalClient()
        self.file_roots = None
        self.pillar_roots = None
        self.sls_dir = None

        try:
            self.load_salt_info()
        except SaltClientError:
            logging.debug("WARNING: SaltClientError")

    def salt_commands_async(self, callback, args, cmd_group, opts=None, timeout=120):
        rets = list()
        for c in cmd_group:
            rets.append((c, self.salt_client.cmd_iter(c['servers'], c['command'], c['arguments'], kwarg=opts,
                                      timeout=timeout, expr_form='list')))
        results = list()
        for retc in rets:
            for r in retc[1]:
                callback(r, retc[0], **args)
                results.append(r)
        return results

    def salt_command(self, target, cmd, arg, opts=None, timeout=120):
        return self.salt_client.cmd(target, cmd, arg, kwarg=opts, timeout=timeout, expr_form='list')

    def run_command(self, target, cmd, shell, timeout=120):
        return self.salt_command(target, 'cmd.run', [cmd], opts={"shell": shell}, timeout=timeout)

    def load_salt_info(self):
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

    def verify_connectivity(self, server, timeout=10):
        return len(self.salt_client.cmd(server, 'test.ping', timeout=timeout)) != 0

    def get_gd_file_name(self, app, name):
        if not os.path.isdir(self.sls_dir):
            os.mkdir(self.sls_dir)
        appdir = "{}/{}".format(self.sls_dir, app)
        if not os.path.isdir(appdir):
            os.mkdir(appdir)
        return "{}/{}.sls".format(appdir, name)

    def get_gitdeploy_entry_name(self, app, gd_name):
         return "{}.{}.{}".format(self.settings['elita.salt.slsdir'], app, gd_name)


    def rm_gitdeploy_yaml(self, gitdeploy):
        name = gitdeploy['name']
        app = gitdeploy['application']
        filename = self.get_gd_file_name(app, name)
        logging.debug("rm_gitdeploy_yaml: gitdeploy: {}/{}".format(app, name))
        logging.debug("rm_gitdeploy_yaml: filename: {}".format(filename))
        if not os.path.isfile(filename):
            logging.debug("rm_gitdeploy_yaml: WARNING: file not found!")
            return
        lock = lockfile.FileLock(filename)
        logging.debug("rm_gitdeploy_yaml: acquiring lock on {}".format(filename))
        lock.acquire(timeout=60)
        os.unlink(filename)
        lock.release()

    def new_gitdeploy_yaml(self, gitdeploy):
        '''Adds new gitdeploy to existing YAML file or creates new YAML file.'''
        name = gitdeploy['name']
        app = gitdeploy['application']
        filename = self.get_gd_file_name(app, name)
        logging.debug("add_gitdeploy_to_yaml: acquiring lock on {}".format(filename))
        lock = lockfile.FileLock(filename)
        lock.acquire(timeout=60)  # throws exception if timeout
        if os.path.isfile(filename):
            logging.debug("add_gitdeploy_to_yaml: existing yaml sls")
            with open(filename, 'r') as f:
                existing = yaml.load(f, Loader=Loader)
        else:
            logging.debug("add_gitdeploy_to_yaml: yaml sls does not exist")
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


