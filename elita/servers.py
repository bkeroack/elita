__author__ = 'bkeroack'

import deployment.salt_control

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
        self.datasvc = datasvc

    def set_server_type(self, rc, name):
        os_type = rc.get_os_text(name)
        self.datasvc.serversvc.ChangeServer(name, {'server_type': os_type})
        return os_type

    def set_server_status(self, rc, name):
        if rc.sc.verify_connectivity(name):
            status = "ok"
        else:
            status = "not connectable (check salt)"

        self.datasvc.serversvc.ChangeServer(name, {'status': status})
        return status == "ok"

    def do_server_setup(self, rc, name, os_type):
        if os_type == "windows":
            # push git wrapper script. run it.
            # make sure git works
            rc.push_files(name, {"salt://elita/files/git_wrapper_setup.ps1": 'C:\\git_wrapper_setup.ps1'})
            rc.run_powershell_script(name, 'C:\\git_wrapper_setup.ps1')
            if 'not recognized as an internal or external command' in rc.run_shell_command(name, 'git')[name]:
                status = 'git not available'
            else:
                status = 'ok, initialized'
            self.datasvc.serversvc.ChangeServer(name, {'status': status})

    def new(self, name):
        sc = deployment.salt_control.SaltController(self.datasvc.settings)
        rc = deployment.salt_control.RemoteCommands(sc)

        ost = self.set_server_type(rc, name)
        if self.set_server_status(rc, name):
            self.do_server_setup(rc, name, ost)
