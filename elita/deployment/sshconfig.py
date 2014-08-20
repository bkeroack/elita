import logging
import os
import stat
import elita.util
import lockfile
import tempfile

import elita.util.type_check
from salt_control import OSTypes, RemoteCommands

ELITA_USER = "elita"
#remote key locations
WINDOWS_KEY_LOCATION = 'C:\Program Files (x86)\Git\.ssh'
UNIX_KEY_LOCATION = '~/.ssh'
UNIX_MINION_USER = 'root'  # hack

class UnknownGitproviderType(Exception):
    pass

class SSHController:
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self):
        pass

    def get_alias_block(self, alias_name, real_hostname, keyfile, username='git'):
        '''
        Return the ssh config block for the requested alias. We use tabs to make it easier to parse if we ever need to
        in the future.
        '''
        return """
Host {alias}
\tHostname {hostname}
\tUser {username}
\tPreferredAuthentications publickey
\tStrictHostKeyChecking no
\tIdentityFile "{key}"

""".format(alias=alias_name, hostname=real_hostname, username=username, key=keyfile)

    def get_local_ssh_dir(self):
        '''
        Get path of local .ssh config and create it if necessary
        '''
        home_dir = os.path.expanduser('~{}'.format(ELITA_USER))
        home_sshdir = os.path.join(home_dir, ".ssh")
        if not os.path.isdir(home_sshdir):
            os.mkdir(home_sshdir)
        return home_sshdir

    def get_key_name(self, application, gitrepo_name):
        return "{}-{}".format(application, gitrepo_name)

    def get_alias(self, gitrepo_name, app):
        return "{}-{}".format(app, gitrepo_name)

    def get_full_alias_uri(self, gitrepo):
        '''
        Get the full aliased URI for a given gitrepo
        '''
        assert gitrepo
        assert elita.util.type_check.is_dictlike(gitrepo)
        assert 'gitprovider' in gitrepo
        assert elita.util.type_check.is_dictlike(gitrepo['gitprovider'])
        assert 'type' in gitrepo['gitprovider']     # make sure gitprovider is dereferenced

        alias_host = self.get_alias(gitrepo['name'], gitrepo['application'])
        if gitrepo['gitprovider']['type'] == 'bitbucket':
            return gitrepo['uri'].replace('bitbucket.org', alias_host)
        elif gitrepo['gitprovider']['type'] == 'github':
            return gitrepo['uri'].replace('github.com', alias_host)
        else:
            raise UnknownGitproviderType

    def add_local_alias(self, alias_block):
        '''
        Add ssh alias (for gitdeploy most likely) to the local ssh config
        '''
        ssh_config = os.path.join(self.get_local_ssh_dir(), "config")
        lock = lockfile.FileLock(ssh_config)
        lock.acquire(timeout=60)
        with open(ssh_config, 'a') as f:
            f.write(alias_block)
        os.chmod(ssh_config, stat.S_IWUSR | stat.S_IRUSR)
        lock.release()

    def add_remote_alias(self, remote_controller, server_list, sshconf, alias_block):
        '''
        Add ssh alias to remote ssh config via file.append

        This is pretty hacky since the alias could already exist and this will just append to the config endlessly,
        but fixing that would involve parsing the whole config and that gets complicated.
        '''
        remote_controller.touch(server_list, sshconf)
        return remote_controller.append_to_file(server_list, sshconf, alias_block)


    def write_local_keys(self, application, gitrepo_type, gitrepo_name, private_key_data, public_key_data):
        '''
        Write key data to named key files for gitrepo
        '''
        home_sshdir = self.get_local_ssh_dir()
        keyname = self.get_key_name(application, gitrepo_name)
        priv_key_name = os.path.join(home_sshdir, keyname)
        pub_key_name = "{}.pub".format(priv_key_name)

        logging.debug("write_local_keys: writing keypairs")
        with open(pub_key_name, 'w') as f:
            f.write(public_key_data.decode('string_escape'))

        with open(priv_key_name, 'w') as f:
            f.write(private_key_data.decode('string_escape'))

        logging.debug("write_local_keys: chmod private key to owner read/write only")
        os.chmod(priv_key_name, stat.S_IWUSR | stat.S_IRUSR)

        logging.debug("write_local_keys: adding alias to ssh config")
        alias_name = self.get_alias(gitrepo_name, application)
        alias_block = self.get_alias_block(alias_name, "bitbucket.org" if gitrepo_type == 'bitbucket' else 'github.com',
                                           priv_key_name)
        self.add_local_alias(alias_block)
        return alias_name

    def create_key_dir(self, remote_controller, server_list):
        '''
        Create platform-specific directory to hold ssh config and keys
        @type remote_controller: RemoteCommands
        '''
        assert remote_controller and server_list
        assert isinstance(remote_controller, RemoteCommands)
        assert elita.util.type_check.is_seq(server_list)

        servers_by_os = remote_controller.group_remote_servers_by_os(server_list)
        results = {'windows': dict(), 'unix': dict()}
        if len(servers_by_os['windows']) > 0:
            results['windows'] = remote_controller.create_directory(servers_by_os['windows'], WINDOWS_KEY_LOCATION)
        if len(servers_by_os['unix']) > 0:
            results['unix'] = remote_controller.create_directory(servers_by_os['unix'], UNIX_KEY_LOCATION)
        #merge results
        return dict({s: results['windows'][s] for s in results['windows']}, **{s: results['unix'][s] for s in results['unix']})

    def push_remote_keys(self, remote_controller, server_list, application, gitrepo_name, gitrepo_type, privkey_data, pubkey_data):
        '''
        Write keydata to temp files, push to remote servers. Add alias to remote ssh config
        '''

        f_pub, tf_pub = tempfile.mkstemp(text=True)
        with open(tf_pub, 'w') as f:
            f.write(pubkey_data.decode('string_escape'))

        f_priv, tf_priv = tempfile.mkstemp(text=True)
        with open(tf_priv, 'w') as f:
            f.write(privkey_data.decode('string_escape'))

        keyname = self.get_key_name(application, gitrepo_name)
        real_hostname = "bitbucket.org" if gitrepo_type == "bitbucket" else "github.com"
        servers_by_os = remote_controller.group_remote_servers_by_os(server_list)

        res_win = dict()
        if len(servers_by_os['windows']) > 0:
            local_to_remote_mapping = {
                tf_pub: "{}\{}.pub".format(WINDOWS_KEY_LOCATION, keyname),
                tf_priv: "{}\{}".format(WINDOWS_KEY_LOCATION, keyname)
            }
            alias_block = self.get_alias_block(self.get_alias(gitrepo_name, application), real_hostname,
                                               local_to_remote_mapping[tf_priv])
            sshconf = "{}\\config".format(WINDOWS_KEY_LOCATION)
            res_win['push_files'] = remote_controller.push_files(servers_by_os['windows'], local_to_remote_mapping)
            res_win['add_alias'] = self.add_remote_alias(remote_controller, servers_by_os['windows'], sshconf, alias_block)

        res_unix = dict()
        if len(servers_by_os['unix']) > 0:
            local_to_remote_mapping = {
                tf_pub: os.path.join(UNIX_KEY_LOCATION, "{}.pub".format(keyname)),
                tf_priv: os.path.join(UNIX_KEY_LOCATION, keyname)
            }
            alias_block = self.get_alias_block(self.get_alias(gitrepo_name, application), real_hostname,
                                               local_to_remote_mapping[tf_priv])
            sshconf = os.path.join(UNIX_KEY_LOCATION, "config")
            res_unix['push_files'] = remote_controller.push_files(servers_by_os['unix'], local_to_remote_mapping,
                                                                  mode="600")
            res_unix['add_alias'] = self.add_remote_alias(remote_controller, servers_by_os['unix'], sshconf, alias_block)

        os.unlink(tf_pub)
        os.unlink(tf_priv)

        return dict(res_win, **res_unix)