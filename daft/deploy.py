__author__ = 'bkeroack'

import util
import gitservice
import salt_control

#async callable
def run_deploy(datasvc, application, build_name, servers, gitdeploys, deployment):
    dc = DeployController(datasvc, application, build_name, servers, gitdeploys)
    dc.run()
    datasvc.deploysvc.UpdateDeployment({"results": "complete"})
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
    def __init__(self, datasvc, app_name, build_name, servers, gitdeploys):
        self.datasvc = datasvc
        self.application = app_name
        self.build_name = build_name
        self.build_doc = datasvc.buildsvc.GetBuildDoc(app_name, build_name)
        self.servers = servers
        self.gitdeploys = gitdeploys
        self.sc = salt_control.SaltController(datasvc.settings)
        self.rc = salt_control.RemoteCommands(self.sc)

    def add_msg(self, msg):
        util.debugLog(self, msg)
        self.datasvc.jobsvc.NewJobData({
            "DeployController": {
                "message": msg
            }
        })

    def push_to_gitdeploy(self, gddoc):
        self.add_msg("Starting push to gitdeploy '{}' for application '{}'".format(gddoc['name'], self.application))
        package = gddoc['package']
        package_doc = self.build_doc['packages'][package]
        gdm = gitservice.GitDeployManager(gddoc, self.datasvc.settings)
        self.add_msg("checking out default git branch")
        res = gdm.checkout_default_branch()
        self.add_msg("git checkout result: {}".format(res))
        self.add_msg("decompressing package to master gitdeploy repo")
        gdm.decompress_to_repo(package_doc)
        self.add_msg("checking for changes")
        res = gdm.check_repo_status()
        self.add_msg("git status result: {}".format(res))
        if "nothing to commit" in res:
            self.add_msg("no changes to commit/push")
        else:
            self.add_msg("adding changed files to commit")
            res = gdm.add_files_to_repo()
            self.add_msg("git add result: {}".format(res))
            self.add_msg("committing changes")
            res = gdm.commit_to_repo(self.build_name)
            self.add_msg("git commit result: {}".format(res))
            self.add_msg("pushing changes to git provider")
            res = gdm.push_repo()
            self.add_msg("git push result: {}".format(res))
        self.add_msg("Finished gitdeploy push")

    def salt_checkout_branch(self, gddoc):
        branch = gddoc['location']['default_branch']
        path = gddoc['location']['path']
        self.add_msg("Checking out branch: {} on path: {}".format(branch, path))
        res = self.rc.checkout_branch(self.servers, path, branch)
        self.add_msg("git checkout {} result: {}".format(branch, res))

    def salt_highstate_server(self):
        self.add_msg("Starting highstate deployment on server_spec: {}".format(self.servers))
        res = self.rc.highstate(self.servers)
        self.add_msg({"highstate_result": res})
        self.add_msg("Finished highstate deployment on server_spec: {}".format(self.servers))

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
                                                                                               self.servers))
        for gd in self.gitdeploys:
            gddoc = self.datasvc.gitsvc.GetGitDeploy(self.application, gd)
            self.push_to_gitdeploy(gddoc)
            self.salt_checkout_branch(gddoc)

        self.salt_highstate_server()

        self.add_msg("Finished gitdeploy: build: {}; application: {}; server spec: {}".format(self.build_name,
                                                                                               self.application,
                                                                                               self.servers))
