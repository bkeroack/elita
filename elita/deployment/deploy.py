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


    def add_msg(self, msg):
        elita.util.debugLog(self, msg)
        self.datasvc.jobsvc.NewJobData({"DeployController": msg})


    def error_msg(self, msg):
        elita.util.debugLog(self, msg)
        self.datasvc.jobsvc.NewJobData({"error": msg})


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

        #we assume a single rolling_divisor for all rolling groups
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
                batches[0]['gitdeploys'] += non_rolling_group_docs[nrg]['gitdeploys']

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
            self.add_msg({
                "RollingDeployment": {
                    "batch_count": len(batches),
                    "rolling_groups": rolling_groups,
                    "nonrolling_groups": self.get_nonrolling_groups(rolling_groups, target['groups']),
                    "divisor": rolling_divisor
                }
            })

            for i, b in enumerate(batches):
                self.add_msg("Starting batch {}".format(i))
                self.add_msg({"batch_target": b})

                if not self.dc.run(application, build_name, b['servers'], b['gitdeploys'], i):
                    self.error_msg("error executing batch {}".format(i))
                    return False
                self.add_msg("Done with batch {}".format(i))
            self.add_msg("Deployment finished")
        else:
            self.add_msg({"ManualDeployment": target})
            if not self.dc.run(application, build_name, target['servers'], target['gitdeploys'], 0):
                self.error_msg("error executing deployment")
                return False
            self.add_msg("Deployment finished")
        return True



class DeployController(GenericDeployController):

    def push_to_gitdeploy(self, gdm, gddoc):
        self.add_msg("Starting push to gitdeploy: {}".format(gddoc['name']))
        package = gddoc['package']
        package_doc = self.build_doc['packages'][package]
        self.current_step += 1
        #self.add_msg("Checking out default git branch")
        res = gdm.checkout_default_branch()
        elita.util.debugLog(self, "git checkout output: {}".format(str(res)))
        self.current_step += 1
        if gdm.last_build == self.build_name:
            self.add_msg("Build already committed to local gitrepo; skipping package decompression")
            self.current_step += 5
        else:
            self.add_msg("Decompressing package to master gitdeploy repo")
            gdm.decompress_to_repo(package_doc)
            self.current_step += 1
            elita.util.debugLog(self, "Checking for changes")
            res = gdm.check_repo_status()
            elita.util.debugLog(self, "git status results: {}".format(str(res)))

            if "nothing to commit" in res:
                self.current_step += 4
                self.add_msg("No changes to commit/push")
            else:
                self.current_step += 1
                self.add_msg("Adding changed files to commit")
                res = gdm.add_files_to_repo()
                elita.util.debugLog(self, "git add result: {}".format(str(res)))
                self.current_step += 1
                self.add_msg("Committing changes")
                res = gdm.commit_to_repo(self.build_name)
                elita.util.debugLog(self, "git commit result: {}".format(str(res)))
                self.current_step += 1
                res = gdm.inspect_latest_diff()
                elita.util.debugLog(self, "inspect diff result: {}".format(str(res)))
                self.current_step += 1
                self.add_msg("Pushing changes to git provider")
                res = gdm.push_repo()
                elita.util.debugLog(self, "git push result: {}".format(str(res)))
            gdm.update_repo_last_build(self.build_name)
        self.add_msg("Finished gitdeploy push")

    def salt_checkout_branch(self, gddoc):
        branch = gddoc['location']['default_branch']
        path = gddoc['location']['path']
        self.current_step += 1
        self.add_msg("Discarding uncommitted changes and checking out gitdeploy branch")
        res = self.rc.discard_git_changes(self.servers, path)
        elita.util.debugLog(self, "discard git changes result: {}".format(str(res)))
        res = self.rc.checkout_branch(self.servers, path, branch)
        elita.util.debugLog(self, "git checkout result: {}".format(str(res)))

    def pull_callback(self, results, tag):
        self.add_msg("pull tag: {} result: {}".format(tag, results))

    def git_pull_gitdeploys(self):
        #until salt Helium is released, we can only execute an SLS *file* as opposed to a single module call
        sls_list = [self.sc.get_gitdeploy_entry_name(self.application, gd) for gd in self.gitdeploys]
        self.current_step += 1
        self.add_msg("Executing states and git pull: {}".format(self.servers))
        callback = {
            'func': self.pull_callback,
            'tag': self.gitdeploys
        }
        res = self.rc.run_sls_async(callback, self.servers, sls_list)
        elita.util.debugLog(self, "git_pull_gitdeploys: results: {}".format(res))
        errors = dict()
        successes = dict()
        for r in res:
            for host in r:
                for cmd in r[host]:
                    if "gitdeploy" in cmd:
                        if "result" in r[host][cmd]:
                            if not r[host][cmd]["result"]:
                                errors[host] = r[host][cmd]["changes"] if "changes" in r[host][cmd] else r[host][cmd]
                            else:
                                if host not in successes:
                                    successes[host] = dict()
                                module, state, command, subcommand = str(cmd).split('|')
                                if state not in successes[host]:
                                    successes[host][state] = dict()
                                successes[host][state][command] = {
                                    "stdout": r[host][cmd]["changes"]["stdout"],
                                    "stderr": r[host][cmd]["changes"]["stderr"],
                                    "retcode": r[host][cmd]["changes"]["retcode"],
                                }
        if len(errors) > 0:
            elita.util.debugLog(self, "SLS error servers: {}".format(errors.keys()))
            elita.util.debugLog(self, "SLS error responses: {}".format(errors))
            self.error_msg("Errors detected in sls execution on servers: {}".format(errors.keys()))
        elif len(successes) > 0:
            self.add_msg("Successful git pull and state execution")
        self.current_step += 1
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
        self.total_steps = len(self.gitdeploys) * 11

        self.current_step += 1

        for gd in self.gitdeploys:
            self.add_msg("Processing gitdeploy: {}".format(gd))
            gddoc = self.datasvc.gitsvc.GetGitDeploy(self.application, gd)
            gdm = gitservice.GitDeployManager(gddoc, self.datasvc)
            self.push_to_gitdeploy(gdm, gddoc)
            self.salt_checkout_branch(gddoc)

        self.git_pull_gitdeploys()

        self.current_step = self.total_steps

        return True

