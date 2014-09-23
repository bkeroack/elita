__author__ = 'bkeroack'

import deployment.salt_control
import deployment.sshconfig

def setup_new_server(datasvc, name):
    '''
    Do any initial server setup so it works for elita.

    Initially we just check if it's a Windows server and if so set up the git wrapper. At some point maybe we should
    verify that git is available (for all platforms) and whatever else is needed.
    '''
    ss = ServerSetup(datasvc)
    ss.new(name)

class ServerSetup:
    '''
    Initialization routines for new servers.
    '''
    def __init__(self, datasvc):
        '''
        @type datasvc: elita.models.DataService
        '''
        self.datasvc = datasvc

    def set_server_type(self, rc, name):
        os_type = rc.get_os_text(name)
        self.datasvc.serversvc.UpdateServer(name, {'server_type': os_type})
        return os_type

    def set_server_status(self, rc, name):
        if rc.sc.verify_connectivity(name):
            status = "ok"
        else:
            status = "not connectable (check salt)"

        self.datasvc.serversvc.UpdateServer(name, {'status': status})
        return status == "ok"

    def do_server_setup(self, rc, name, os_type):
        #create key/config dirs
        sshc = deployment.sshconfig.SSHController()
        sshc.create_key_dir(rc, [name])

        if os_type == "windows":
            # push git wrapper script. run it.
            # make sure git works
            wrapper_setup_path = "C:/git_wrapper_setup.ps1"
            rc.rm_file_if_exists([name], wrapper_setup_path)
            rc.push_files([name], {"salt://elita/files/win/git_wrapper_setup.ps1": wrapper_setup_path})
            rc.run_powershell_script([name], wrapper_setup_path)
            if 'not recognized as an internal or external command' in rc.run_shell_command([name], 'git')[name]:
                status = 'git not available'
            else:
                self.datasvc.jobsvc.NewJobData({'note': 'IMPORTANT!! For the Windows git wrapper script to take effect '
                                                        '(necessary for key/hostname management), you *must* either '
                                                        'reboot or restart salt-minion at a minimum! Any git operation '
                                                        'will fail until this happens.'})
                status = 'ok, initialized'
        else:
            status = 'ok, initialized'
        self.datasvc.serversvc.UpdateServer(name, {'status': status})

    def new(self, name):
        sc = deployment.salt_control.SaltController(self.datasvc)
        rc = deployment.salt_control.RemoteCommands(sc)

        ost = self.set_server_type(rc, name)
        if self.set_server_status(rc, name):
            self.do_server_setup(rc, name, ost)
