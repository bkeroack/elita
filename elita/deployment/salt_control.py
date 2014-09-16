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
import copy
import elita.deployment.gitservice

try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

import elita.util
import elita.util.type_check

__author__ = 'bkeroack'

class FatalSaltError(Exception):
    pass

class OSTypes:
    Windows = 0
    Unix_like = 1

class RemoteCommands:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, sc):
        '''
        @type sc: SaltController
        '''
        assert sc
        assert isinstance(sc, SaltController)
        self.sc = sc

    def get_os(self, server):
        resp = self.sc.salt_command(server, 'grains.item', ["os"])
        logging.debug("get_os: resp: {}".format(resp))
        return OSTypes.Windows if resp[server]['os'] == "Windows" else OSTypes.Unix_like

    def get_os_text(self, server):
        ost = self.get_os(server)
        if ost == OSTypes.Windows:
            return "windows"
        elif ost == OSTypes.Unix_like:
            return "unix"
        else:
            return "unknown"

    def group_remote_servers_by_os(self, server_list):
        '''
        Determine which servers are Windows and which are Unix-like, so we know where to push keys, etc to.
        '''
        unix_servers = list()
        win_servers = list()
        for s in server_list:
            ost = self.get_os(s)
            if ost == OSTypes.Windows:
                win_servers.append(s)
            elif ost == OSTypes.Unix_like:
                unix_servers.append(s)
        return {
            'unix': unix_servers,
            'windows': win_servers
        }

    def get_remote_home(self, server_list):
        '''
        Get shell expansion of ~ on remote servers (home of user salt-minion is running as)

        @type server_list: list(str)
        '''
        assert server_list
        assert elita.util.type_check.is_seq(server_list)
        servers_by_os = self.group_remote_servers_by_os(server_list)
        res_win = self.sc.salt_command(servers_by_os['windows'], 'cmd.run', ['$env:userprofile'],
                                        opts={'shell': 'powershell'}) if len(servers_by_os['windows']) > 0 else {}
        res_unix = self.sc.salt_command(servers_by_os['unix'], 'cmd.run', ['eval "echo ~$(whoami)"']) \
            if len(servers_by_os['unix']) > 0 else {}
        assert len(set(res_unix.keys()).intersection(set(res_win.keys()))) == 0     # no common keys
        return dict(res_unix, **res_win)

    def get_home_expanded_path(self, server_list, path_list):
        '''
        Given a list of servers and a list of paths with '~' in them, return absolute paths

        @type server_list: list(str)
        @type path_list: list(str)
        '''

        assert server_list and path_list
        assert elita.util.type_check.is_seq(server_list)
        assert elita.util.type_check.is_seq(path_list)
        assert all(['~' in p for p in path_list])

        path_by_server = {item[0]: item[1] for item in zip(server_list, path_list)}
        home_dirs = self.get_remote_home(server_list)
        return {s: path_by_server[s].replace('~', home_dirs[s]) for s in path_by_server}

    def create_directory(self, server_list, path):
        assert isinstance(server_list, list)
        return self.sc.salt_command(server_list, 'file.mkdir', [path])

    def delete_directory_win(self, server_list, path):
        return self.sc.salt_command(server_list, 'cmd.run', ["if (Test-Path {path}) {{ Remove-Item -Recurse -Force {path} }}".format(path=path)],
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

    def _get_salt_uri(self, local_path):
        '''
        For pushing local files to remote servers, need to copy it to a random location in salt tree
        so we can push via cp.get_file. This file should be deleted after that call returns.
        '''

        r_postfix = ''.join(random.sample(string.letters + string.digits, 20))
        root = self.sc.sls_dir
        newname = os.path.basename(local_path) + r_postfix
        new_fullpath = "{}/{}".format(root, newname)
        shutil.copy(local_path, new_fullpath)
        return 'salt://{}/{}'.format(self.sc.settings['elita.salt.slsdir'], newname), new_fullpath

    def push_files(self, target, local_remote_path_mapping, mode=None):
        '''
        Push a list of files to corresponding remote paths. Make sure each remote path exists first.
        Do all pushes in a single salt call (faster).

        Note that these must be files, not directories.

        local_remote_path_mapping = { 'local_path': 'remote_path' }
        '''
        assert target and local_remote_path_mapping
        assert elita.util.type_check.is_seq(target)
        assert elita.util.type_check.is_dictlike(local_remote_path_mapping)
        # paths can't be directories
        assert all([p[-1] != '/' and local_remote_path_mapping[p][-1] != '/' for p in local_remote_path_mapping])
        assert elita.util.type_check.is_optional_str(mode)

        calls = list()
        params = list()
        temp_files = list()

        #delete remote path first
        logging.debug("removing any existing remote_path")
        for local_path in local_remote_path_mapping:
            self.rm_dir_if_exists(target, local_remote_path_mapping[local_path])

        for local_path in local_remote_path_mapping:
            if 'salt://' in local_path:
                salt_uri = local_path
            else:
                salt_uri, tf = self._get_salt_uri(local_path)
                temp_files.append(tf)
            remote_path = local_remote_path_mapping[local_path]
            expanded_path = self.get_home_expanded_path(target, [remote_path])[target[0]] if '~' in remote_path else remote_path
            calls.append('cp.get_file')
            if mode:
                calls.append('file.set_mode')
            params.append([salt_uri, expanded_path])
            if mode:
                params.append([expanded_path, mode])
            logging.debug("push_files: remote_path: {}".format(expanded_path))

        rets = self.sc.salt_command(target, calls, params, opts={'makedirs': True})
        for tf in temp_files:
            os.unlink(tf)
        return rets

    def rm_file_if_exists(self, target, path):
        '''
        Remove target directory if it exists
        '''
        assert target and path
        assert elita.util.type_check.is_seq(target)
        assert elita.util.type_check.is_string(path)
        for server in target:
            expanded_path = self.get_home_expanded_path([server], [path])[server] if '~' in path else path
            file_exists = self.sc.salt_command([server], "file.file_exists", [expanded_path])
            if server in file_exists and file_exists[server]:
                self.sc.salt_command([server], "file.remove", [expanded_path])

    def rm_dir_if_exists(self, target, path):
        '''
        Remove target directory if it exists
        '''
        assert target and path
        assert elita.util.type_check.is_seq(target)
        assert elita.util.type_check.is_string(path)
        servers_by_os = self.group_remote_servers_by_os(target)
        for server in target:
            expanded_path = self.get_home_expanded_path([server], [path])[server] if '~' in path else path
            file_exists = self.sc.salt_command([server], "file.file_exists", [expanded_path])
            if file_exists[server]:
                self.sc.salt_command([server], "file.remove", [expanded_path])
                break
            dir_exists = self.sc.salt_command([server], "file.directory_exists", [expanded_path])
            if dir_exists[server]:
                #have to delete recursively, and no built-in salt module supports that
                if server in servers_by_os['unix']:
                    self.sc.salt_command([server], 'cmd.run', ['rm -rf {}'.format(expanded_path)])
                elif server in servers_by_os['windows']:
                    self.sc.salt_command([server], 'cmd.run', ['Remove-Item -Recurse -Force {}'.format(expanded_path)],
                                         opts={'shell': 'powershell'})
                else:
                    raise FatalSaltError

    def run_powershell_script(self, server_list, script_path):
        return self.sc.salt_command(server_list, 'cmd.run', [script_path], opts={'shell': 'powershell'})

    def run_shell_command(self, server_list, cmd):
        return self.sc.salt_command(server_list, 'cmd.run', [cmd])

    def touch(self, server_list, remote_path):
        #hack: assuming all servers in server_list have the same ~ path expansion
        expanded_path = self.get_home_expanded_path(server_list, [remote_path])[server_list[0]] if '~' in remote_path else remote_path
        return self.sc.salt_command(server_list, 'file.touch', [expanded_path])

    def ping(self, server_list, timeout=10):
        return self.sc.salt_command(server_list, 'test.ping', arg=[], timeout=timeout)

    def append_to_file(self, server_list, remote_path, text_block):
        #hack: assuming all servers in server_list have the same ~ path expansion
        expanded_path = self.get_home_expanded_path(server_list, [remote_path])[server_list[0]] if '~' in remote_path else remote_path
        return self.sc.salt_command(server_list, 'file.append', [expanded_path, text_block])

    def clone_repo(self, server_list, repo_uri, dest):
        assert server_list and repo_uri and dest
        assert elita.util.type_check.is_seq(server_list)
        assert elita.util.type_check.is_string(repo_uri)
        assert elita.util.type_check.is_string(dest)
        logging.debug("clone_repo: deleting remote destination if necessary")
        self.rm_dir_if_exists(server_list, dest)
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
                                    opts={'cwd': location}, timeout=30)

    def set_user_git(self, server_list, location, email, name):
        return {
            "name": self.sc.salt_command(server_list, 'cmd.run', ['git config user.name "{}"'.format(name)],
                                         opts={'cwd': location}, timeout=30),
            "email": self.sc.salt_command(server_list, 'cmd.run', ['git config user.email "{}"'.format(email)],
                                         opts={'cwd': location}, timeout=30)
        }

    def set_git_autocrlf(self, server_list, location):
        return self.sc.salt_command(server_list, 'cmd.run', ['git config core.autocrlf input'],
                                    opts={'cwd': location}, timeout=30)

    def set_git_push_url(self, server_list, location, url):
        return self.sc.salt_command(server_list, 'cmd.run', ['git remote set-url --push origin "{}"'.format(url)],
                                    opts={'cwd': location}, timeout=30)

    # def set_git_upstream(self, server_list, location, branch):
    #     return self.sc.salt_command(server_list, 'cmd.run',
    #                                 ['git branch --set-upstream-to=origin/{} {}'.format(branch, branch)],
    #                                 opts={'cwd': location}, timeout=30)

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
        return self.sc.salt_commands_async(callback, args, cmd_group, timeout=600, opts={'concurrent': True})

class SaltController:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, datasvc):
        '''
        @type datasvc: elita.models.DataService
        '''
        self.settings = datasvc.settings
        self.salt_client = salt.client.LocalClient()
        self.datasvc = datasvc
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
                callback(r, retc[0]['arguments'], **args)
                results.append(r)
        return results

    def salt_command(self, target, cmd, arg, opts=None, timeout=20):
        results = self.salt_client.cmd(target, cmd, arg, kwarg=opts, timeout=timeout, expr_form='list')
        results_sanitized = copy.deepcopy(results)
        elita.util.change_dict_keys(results_sanitized, '.', '_')    # remove '.' in keys for mongo
        # try to detect if there was an error or exception in any results
        for path in elita.util.paths_from_nested_dict(results):
            if elita.util.type_check.is_string(path[-1]):
                if not all([word.lower() not in path[-1].lower() for word in ('error', 'exception', 'traceback', 'fatal')]):
                    self.datasvc.jobsvc.NewJobData({'error': 'error detected in salt command results',
                                                    'detected_in': path[-1],
                                                    'all_results': results_sanitized,
                                                    'target': target,
                                                    'cmd': cmd,
                                                    'arg': arg})
                    raise FatalSaltError
        self.datasvc.jobsvc.NewJobData({'salt_command': {'target': target, 'cmd': cmd, 'arg': arg,
                                                         'results': results_sanitized}})
        return results

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
            if not existing:    # if empty file this will be None
                existing = dict()
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


