__author__ = 'bkeroack'

import util
import gitservice
import salt_control

#async callable
def run_deploy(datasvc, application, build_name, server_spec):
    dc = DeployController(datasvc, application, build_name, server_spec)
    dc.run()
    return {"deploy_status": "complete"}

def validate_server_specs(server_specs):
    if not isinstance(server_specs, dict):
        return False, "must be dict"
    for k in ('type', 'spec', 'gitdeploys'):
        if k not in server_specs:
            return False, "server spec dict must have '{}' key".format(k)
    if server_specs['type'] != 'list' and type != 'glob':
        return False, "type must be 'list' or 'glob'"
    if server_specs['type'] == 'list':
        if not isinstance(server_specs['spec'], list):
            return False, "invalid spec for type 'list' [need list]"
    elif server_specs['type'] == 'glob':
        if not isinstance(server_specs['spec'], str):
            return False, "invalid spec for type 'glob' [need str]"
    if not isinstance(server_specs['gitdeploys'], list):
        return False, "invalid gitdeploys [need list]"
    return True, None

class DeployController:
    def __init__(self, datasvc, app_name, build_name, server_specs):
        self.datasvc = datasvc
        self.application = app_name
        self.build_name = build_name
        self.build_doc = datasvc.buildsvc.GetBuildDoc(app_name, build_name)
        self.server_specs = server_specs
        self.sc = salt_control.SaltController(datasvc.settings)
        self.rc = salt_control.RemoteCommands(self.sc)

    def add_msg(self, msg):
        util.debugLog(self, msg)
        self.datasvc.jobsvc.NewJobData({
            "DeployController": {
                "message": msg
            }
        })

    def push_to_gitdeploy(self, gdname):
        self.add_msg("Starting gitdeploy push to gitdeploy '{}' for application '{}'".format(self.gitdeploy['name'],
                                                                                             self.application))
        gddoc = self.datasvc.gitsvc.GetGitDeploy(self.application, gdname)
        package = gddoc['package']
        package_doc = self.build_doc['packages'][package]
        gdm = gitservice.GitDeployManager(gddoc, self.datasvc.settings)
        self.add_msg("decompressing package to master gitdeploy repo")
        gdm.decompress_to_repo(package_doc)
        self.add_msg("adding changed files to commit")
        res = gdm.add_files_to_repo()
        self.add_msg("git add result: {}".format(res))
        self.add_msg("committing changes")
        res = gdm.commit_to_repo(self.build_name)
        self.add_msg("git commit result: {}".format(res))
        self.add_msg("pushing changes to git provider")
        res = gdm.push_repo()
        self.add_msg("git push result: {}".format(res))
        self.add_msg("Finished gitdeploy push for {}")

    def salt_highstate_server(self, server_spec):
        self.add_msg("Starting highstate deployment on server_spec: {}".format(server_spec))
        res = self.rc.highstate(server_spec)
        self.add_msg({"highstate_result": res})
        self.add_msg("Finished highstate deployment on server_spec: {}".format(server_spec))

    def run(self):
        '''
        1. Decompress build to gitdeploy dir and push
            a. Iterate over server_specs to build list of gitdeploys to push to (make sure no dupes)
            b. Push desired build to gitdeploys
        2. Issue salt highstate
            a. Iterate over server_specs, issue highstate call for each
        '''
        self.add_msg("Beginning gitdeploy: build: {}; application: {}; server spec: {}".format(self.build_name,
                                                                                               self.application,
                                                                                               self.server_specs))
        for gd in self.server_specs['gitdeploys']:
            self.push_to_gitdeploy(gd)
        self.salt_highstate_server(self.server_specs['spec'])

        self.add_msg("Finished gitdeploy: build: {}; application: {}; server spec: {}".format(self.build_name,
                                                                                               self.application,
                                                                                               self.server_specs))
