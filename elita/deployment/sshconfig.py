import logging
import os
import stat
import elita.util
import lockfile

ELITA_USER = "elita"

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
\tIdentityFile {key}

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