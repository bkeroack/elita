__author__ = 'bkeroack'

import sys
import traceback
import pprint

import elita.util
import gitservice
import salt_control

#async callable
def run_deploy(datasvc, application, build_name, target, rolling_divisor, deployment):
    sc = salt_control.SaltController(datasvc.settings)
    rc = salt_control.RemoteCommands(sc)


    # normally there's a higher level try/except block for all async actions
    # we want to make sure the error is saved in the deployment object as well, not just the job
    # so we duplicate the functionality here
    try:
        if target['groups']:
            rdc = RollingDeployController(datasvc, rc)
            ret = rdc.run(application, build_name, target, rolling_divisor)
        else:
            dc = DeployController(datasvc, rc)
            ret = dc.run(application, build_name, target['servers'], target['gitdeploys'], 0)
    except:
        exc_type, exc_obj, tb = sys.exc_info()
        f_exc = traceback.format_exception(exc_type, exc_obj, tb)
        results = {
            "error": "unhandled exception during callable!",
            "exception": f_exc
        }
        elita.util.debugLog(run_deploy, "EXCEPTION: {}".format(f_exc))
        datasvc.deploysvc.UpdateDeployment(application, deployment, {"status": "error"})
        return {"deploy_status": "error", "details": results}
    datasvc.deploysvc.UpdateDeployment(application, deployment, {"status": "complete" if ret else "error"})
    return {"deploy_status": "done" if ret else "error"}

class GenericDeployController:
    def __init__(self, datasvc, remote_controller):
        self.datasvc = datasvc
        self.rc = remote_controller
        self.sc = remote_controller.sc
        self.servers = None
        self.gitdeploys = None
        self.current_step = 0
        self.total_steps = 0
        self.batch_number = 0


    def _push_msg(self, status, msg):
        elita.util.debugLog(self, msg)
        self.datasvc.jobsvc.NewJobData({
            "DeployController": {
                "status": status,
                "batch": self.batch_number,
                "current_step": self.current_step,
                "total_steps": self.total_steps,
                "message": msg,
                "servers": self.servers,
                "gitdeploys": self.gitdeploys
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


class RollingDeployController(GenericDeployController):
    '''Break deployment up into server/gitdeploy batches, then invoke DeployController with them'''
    def __init__(self, datasvc, remote_controller):
        GenericDeployController.__init__(self, datasvc, remote_controller)
        self.dc = DeployController(datasvc, remote_controller)

    def get_nonrolling_groups(self, rolling_groups, all_groups):
        return list(set(all_groups) - set(rolling_groups))

    def compute_batches(self, application, target, rolling_groups, rolling_divisor):
        non_rolling_groups = self.get_nonrolling_groups(rolling_groups, target['groups'])
        non_rolling_group_docs = {g: self.datasvc.groupsvc.GetGroup(application, g) for g in non_rolling_groups}
        rolling_group_docs = {g: self.datasvc.groupsvc.GetGroup(application, g) for g in rolling_groups}
        server_steps = dict()
        batches = list()
        for i in range(0, rolling_divisor):
            batches.append({
                "servers": list(),
                "gitdeploys": list()
            })

        for g in rolling_groups:
            group_servers = self.datasvc.groupsvc.GetGroupServers(application, g)
            group_steps = elita.util.split_seq(group_servers, rolling_divisor)
            server_steps[g] = group_steps

        #coalesce into global batches
        for g in server_steps:
            for i in range(0, rolling_divisor):
                batches[i]['servers'] += server_steps[g][i]
                batches[i]['gitdeploys'] += rolling_group_docs[g]['gitdeploys']

        #add all non-rolling groups to first batch
        if len(non_rolling_groups) > 0:
            non_rolling_group_servers = {g: self.datasvc.groupsvc.GetGroupServers(application, g) for g in non_rolling_groups}
            for nrg in non_rolling_group_servers:
                batches[0]['servers'] += non_rolling_group_servers[nrg]
                batches[0]['gitdeploys'] += non_rolling_group_docs[nrg]

        #dedupe
        for b in batches:
            b['servers'] = list(set(b['servers']))
            b['gitdeploys'] = list(set(b['gitdeploys']))

        return batches

    def run(self, application, build_name, target, rolling_divisor):
        groups = target['groups']
        rolling_groups = [g for g in groups if self.datasvc.groupsvc.GetGroup(application, g)['rolling_deploy']]
        if len(rolling_groups) > 0:
            batches = self.compute_batches(application, target, rolling_groups, rolling_divisor)
            self.add_msg("RollingDeployment", {
                "state": "begin",
                "batch_count": len(batches),
                "rolling_groups": rolling_groups,
                "nonrolling_groups": self.get_nonrolling_groups(rolling_groups, target['groups']),
                "divisor": rolling_divisor
            })
            for i, b in enumerate(batches):
                self.add_msg("RollingDeployment", {
                    "state": "start_batch",
                    "batch_number": i,
                    "batch_target": b
                })

                if not self.dc.run(application, build_name, b['servers'], b['gitdeploys'], i):
                    self.error_msg("error executing batch", {
                        "batch_number": i,
                        "batch_target": b
                    })
                    return False
                self.add_msg("RollingDeployment", {
                    "state": "end_batch",
                    "batch_number": i,
                    "batch_target": b
                })
            batches = self.compute_batches(application, target, rolling_groups, rolling_divisor)
            self.add_msg("RollingDeployment", {
                "state": "end",
                "batch_count": len(batches)
            })
        else:
            self.add_msg("Deployment", {
                "state": "beginning",
                "target": target
            })
            if not self.dc.run(application, build_name, target['servers'], target['gitdeploys'], 0):
                self.error_msg("error executing deployment", {
                    "target": target
                })
                return False
            self.add_msg("Deployment", {
                "state": "done",
                "target": target
            })
        return True



class DeployController(GenericDeployController):

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
        if gdm.last_build == self.build_name:
            self.add_msg(desc="Build already committed to local gitrepo; skipping package decompression", data={})
            self.current_step += 5
        else:
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
            gdm.update_repo_last_build(self.build_name)
        self.add_msg(desc="Finished gitdeploy push", data={})

    def salt_checkout_branch(self, gddoc):
        branch = gddoc['location']['default_branch']
        path = gddoc['location']['path']
        self.current_step += 1

        self.add_msg(desc="Discarding uncommitted changes", data={
            "branch": branch,
            "path": path
        })
        self.add_msg(desc="git result", data={
            "branch": branch,
            "output": self.rc.discard_git_changes(self.servers, path)
        })
        self.add_msg(desc="Checking out gitdeploy branch", data={
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
        return len(errors) == 0

    def run(self, app_name, build_name, servers, gitdeploys, batch_number):
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
        self.batch_number = batch_number
        self.total_steps = (len(self.gitdeploys)*8)+3

        self.current_step += 1
        self.add_msg(desc="Deployment batch", data={
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

        if not self.salt_highstate_server():
            return False

        self.current_step = self.total_steps
        self.add_msg(desc="Finished deployment batch", data={
            "application": self.application,
            "build": self.build_name,
            "servers": self.servers,
            "gitdeploys": self.gitdeploys
        })

        return True

