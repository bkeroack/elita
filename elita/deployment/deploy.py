__author__ = 'bkeroack'

import sys
import traceback

from elita import util
import gitservice
import salt_control

#async callable
def run_deploy(datasvc, application, build_name, servers, gitdeploys, deployment):
    sc = salt_control.SaltController(datasvc.settings)
    rc = salt_control.RemoteCommands(sc)
    dc = DeployController(datasvc, rc)
    # normally there's a higher level try/except block for all async actions
    # we want to make sure the error is saved in the deployment object as well, not just the job
    # so we duplicate the functionality here
    try:
        dc.run(application, build_name, servers, gitdeploys)
    except:
        exc_type, exc_obj, tb = sys.exc_info()
        f_exc = traceback.format_exception(exc_type, exc_obj, tb)
        results = {
            "error": "unhandled exception during callable!",
            "exception": f_exc
        }
        util.debugLog(run_deploy, "EXCEPTION: {}".format(f_exc))
        datasvc.deploysvc.UpdateDeployment(application, deployment, {"status": "error"})
        return {"deploy_status": "error", "details": results}
    datasvc.deploysvc.UpdateDeployment(application, deployment, {"status": "complete"})
    return {"deploy_status": "complete"}

def validate_server_specs(deploy_obj):
    if not isinstance(deploy_obj, dict):
        return False, "must be dict"
    for k in ('servers', 'gitdeploys'):
        if k not in deploy_obj:
            return False, "deployment dict must have '{}' key".format(k)
    if not (isinstance(deploy_obj['servers'], list) or isinstance(deploy_obj['servers'], str)):
        return False, "servers must be a list or string"
    if not isinstance(deploy_obj['gitdeploys'], list):
        return False, "invalid gitdeploys [need list]"
    return True, None

class DeployController:
    def __init__(self, datasvc, remote_controller):
        self.datasvc = datasvc
        self.rc = remote_controller
        self.sc = remote_controller.sc
        self.total_steps = 0
        self.current_step = 0

    def _push_msg(self, status, msg):
        util.debugLog(self, msg)
        self.datasvc.jobsvc.NewJobData({
            "DeployController": {
                "status": status,
                "current_step": self.current_step,
                "total_steps": self.total_steps,
                "message": msg
            }
        })

    def add_msg(self, desc, data):
        self._push_msg("ok", {
            "description": desc,
            "data": data
        })

    def error_msg(self, desc, data):
        self._push_msg("error", {
            "description": desc,
            "data": data
        })

    def done_msg(self, msg):
        self._push_msg("complete", msg)

    def push_to_gitdeploy(self, gddoc):
        self.add_msg(desc="Starting push to gitdeploy", data={
            "gitdeploy": gddoc['name'],
            "application": self.application
        })
        package = gddoc['package']
        package_doc = self.build_doc['packages'][package]
        gdm = gitservice.GitDeployManager(gddoc, self.datasvc)
        self.current_step += 1
        self.add_msg(desc="Checking out default git branch", data={})
        self.add_msg(desc="git checkout complete", data={
            "output": str(gdm.checkout_default_branch())
        })
        self.current_step += 1
        self.add_msg(desc="Decompressing package to master gitdeploy repo", data={})
        gdm.decompress_to_repo(package_doc)
        self.current_step += 1
        self.add_msg(desc="Checking for changes", data={})
        res = gdm.check_repo_status()
        self.add_msg(desc="git status results", data={
            "output": str(res)
        })
        if "nothing to commit" in res:
            self.current_step += 4
            self.add_msg(desc="No changes to commit/push", data={})
        else:
            self.current_step += 1
            self.add_msg(desc="Adding changed files to commit", data={})
            self.add_msg(desc="git add result", data={
                "output": str(gdm.add_files_to_repo())
            })
            self.current_step += 1
            self.add_msg(desc="Committing changes", data={})
            self.add_msg(desc="git commit result", data={
                "output": str(gdm.commit_to_repo(self.build_name))
            })
            self.current_step += 1
            self.add_msg(desc="Inspect latest diff results", data={
                "output": gdm.inspect_latest_diff()
            })
            self.current_step += 1
            self.add_msg(desc="Pushing changes to git provider", data={})
            self.add_msg(desc="git push result", data={
                "output": str(gdm.push_repo())
            })
        self.add_msg(desc="Finished gitdeploy push", data={})

    def salt_checkout_branch(self, gddoc):
        branch = gddoc['location']['default_branch']
        path = gddoc['location']['path']
        self.current_step += 1
        self.add_msg(desc="Checking out gideploy branch", data={
            "branch": branch,
            "path": path
        })
        self.add_msg(desc="git checkout result", data={
            "branch": branch,
            "output": self.rc.checkout_branch(self.servers, path, branch)
        })

    def salt_highstate_server(self):
        self.current_step += 1
        self.add_msg(desc="Starting highstate deployment", data={
            "servers": self.servers
        })
        res = self.rc.highstate(self.servers)
        errors = dict()
        successes = dict()
        for host in res:
            for cmd in res[host]:
                if "gitdeploy" in cmd:
                    if "result" in res[host][cmd]:
                        if not res[host][cmd]["result"]:
                            errors[host] = res[host][cmd]["changes"] if "changes" in res[host][cmd] else res[host][cmd]
                        else:
                            if host not in successes:
                                successes[host] = dict()
                            module, state, command, subcommand = str(cmd).split('|')
                            if state not in successes[host]:
                                successes[host][state] = dict()
                            successes[host][state][command] = {
                                "stdout": res[host][cmd]["changes"]["stdout"],
                                "stderr": res[host][cmd]["changes"]["stderr"],
                                "retcode": res[host][cmd]["changes"]["retcode"],
                            }
        if len(errors) > 0:
            self.error_msg(desc="Errors detected in highstate call", data={
                "success_servers": successes.keys(),
                "error_servers": errors.keys(),
                "error_responses": errors
            })
        if len(successes) > 0:
            self.add_msg(desc="Successfull highstate calls detected", data={
                "success_servers": successes.keys(),
                "success_responses": successes
            })
        self.current_step += 1
        self.add_msg(desc="Finished highstate call", data={
            "servers": self.servers
        })

    def run(self, app_name, build_name, servers, gitdeploys):
        '''
        1. Decompress build to gitdeploy dir and push
            a. Iterate over server_specs to build list of gitdeploys to push to (make sure no dupes)
            b. Push desired build to gitdeploys
        2. Issue salt highstate
            a. Iterate over server_specs, issue highstate call for each
        '''
        self.application = app_name
        self.build_name = build_name
        self.build_doc = self.datasvc.buildsvc.GetBuildDoc(app_name, build_name)
        self.servers = servers
        self.gitdeploys = gitdeploys
        self.total_steps = (len(self.gitdeploys)*8)+3

        self.current_step += 1
        self.add_msg(desc="Beginning deployment", data={
            "application": self.application,
            "build": self.build_name,
            "servers": self.servers,
            "gitdeploys": self.gitdeploys
        })

        for gd in self.gitdeploys:
            self.add_msg(desc="Processing gitdeploy", data={"name": gd})
            gddoc = self.datasvc.gitsvc.GetGitDeploy(self.application, gd)
            self.push_to_gitdeploy(gddoc)
            self.salt_checkout_branch(gddoc)

        self.salt_highstate_server()

        self.current_step = self.total_steps
        self.add_msg(desc="Finished deployment", data={
            "application": self.application,
            "build": self.build_name,
            "servers": self.servers,
            "gitdeploys": self.gitdeploys
        })

        self.done_msg("done")
