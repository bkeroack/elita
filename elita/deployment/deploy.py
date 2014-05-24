__author__ = 'bkeroack'

import sys
import traceback
import time
import multiprocessing

import elita.util
import gitservice
import salt_control
import elita.actions.action

#async callable
def run_deploy(datasvc, application, build_name, target, rolling_divisor, rolling_pause, deployment):

    # normally there's a higher level try/except block for all async actions
    # we want to make sure the error is saved in the deployment object as well, not just the job
    # so we duplicate the functionality here
    try:
        if target['groups']:
            elita.util.debugLog(run_deploy, "Doing rolling deployment")
            rdc = RollingDeployController(datasvc)
            ret = rdc.run(application, build_name, target, rolling_divisor, rolling_pause)
        else:
            elita.util.debugLog(run_deploy, "Doing manual deployment")
            dc = DeployController(datasvc)
            ret, data = dc.run(application, build_name, target['servers'], target['gitdeploys'])
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


class RollingDeployController:
    '''Break deployment up into server/gitdeploy batches, then invoke DeployController with them'''
    def __init__(self, datasvc):
        self.datasvc = datasvc

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

    def run(self, application, build_name, target, rolling_divisor, rolling_pause):

        dc = DeployController(self.datasvc)

        groups = target['groups']
        rolling_groups = [g for g in groups if self.datasvc.groupsvc.GetGroup(application, g)['rolling_deploy']]
        if len(rolling_groups) > 0:
            batches = self.compute_batches(application, target, rolling_groups, rolling_divisor)

            self.datasvc.jobsvc.NewJobData({
                "RollingDeployment": {
                    "batches": len(batches),
                    "batch_data": batches
                }
            })

            changed_gds = list()
            for i, b in enumerate(batches):

                # for first batch, we pass all gitdeploys
                # for subsequent batches we only pass the gitdeploys that we know have changes
                if i == 0:
                    deploy_gds = b['gitdeploys']
                elif i == 1:
                    deploy_gds = changed_gds
                elita.util.debugLog(self, "doing DeployController.run: deploy_gds: {}".format(deploy_gds))
                ok, results = dc.run(application, build_name, b['servers'], deploy_gds, force=i > 0)
                changed_gds = dc.changed_gitdeploys.keys()
                if not ok:
                    self.datasvc.jobsvc.NewJobData({"RollingDeployment": "error"})
                    return False

                if i != (len(batches)-1):
                    time.sleep(rolling_pause)

        else:

            self.datasvc.jobsvc.NewJobData({
                "RollingDeployment": {
                    "batches": 1,
                    "batch_data": [{"servers": target['servers'], "gitdeploys": target["gitdeploys"]}]
                }
            })

            ok, results = dc.run(application, build_name, target['servers'], target['gitdeploys'])
            if not ok:
                self.datasvc.jobsvc.NewJobData({"RollingDeployment": "error"})
                return False

        return True

def determine_deployabe_servers(all_gd_servers, specified_servers):
    return list(set(all_gd_servers).intersection(set(specified_servers)))

def _threadsafe_process_gitdeploy(gddoc, build_doc, servers, queue, settings, job_id):
    '''
    Threadsafe function for processing a single gitdeploy during a deployment.
    Creates own instance of datasvc, etc.
    Pushes changed gitdeploys to a shared queue
    '''

    package = gddoc['package']
    package_doc = build_doc['packages'][package]
    changed = False

    datasvc = elita.actions.action.regen_datasvc(settings, job_id)
    gdm = gitservice.GitDeployManager(gddoc, datasvc)

    res = gdm.checkout_default_branch()
    elita.util.debugLog("_threadsafe_process_gitdeploy", "git checkout output: {}".format(str(res)))

    if gdm.last_build == build_doc['name']:
        datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "already processed"}})
    else:

        datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "processing"}})
        gdm.decompress_to_repo(package_doc)

        elita.util.debugLog("_threadsafe_process_gitdeploy", "Checking for changes")
        res = gdm.check_repo_status()
        elita.util.debugLog("_threadsafe_process_gitdeploy", "git status results: {}".format(str(res)))

        if "nothing to commit" in res:
            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "no changes"}})
        else:

            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "adding to repository"}})
            res = gdm.add_files_to_repo()
            elita.util.debugLog("_threadsafe_process_gitdeploy", "git add result: {}".format(str(res)))

            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "committing"}})
            res = gdm.commit_to_repo(build_doc['name'])
            elita.util.debugLog("_threadsafe_process_gitdeploy", "git commit result: {}".format(str(res)))

            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "checking diff"}})
            res = gdm.inspect_latest_diff()
            elita.util.debugLog("_threadsafe_process_gitdeploy", "inspect diff result: {}".format(str(res)))

            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "pushing"}})
            res = gdm.push_repo()
            elita.util.debugLog("_threadsafe_process_gitdeploy", "git push result: {}".format(str(res)))
            # Changes detected, so add gitdeploy and the relevant servers that must be deployed to
            changed = True
        gdm.update_repo_last_build(build_doc['name'])
    # in the event that the gitrepo hasn't changed, but the gitdeploy indicates that we haven't successfully
    # deployed to all servers, we want to force git pull
    # this can happen if multiple gitdeploys share the same gitrepo
    if gdm.stale:
        changed = True

    if changed:

        queue.put({gddoc['name']: determine_deployabe_servers(gddoc['servers'], servers)})

        #for all that have changed, do a remote forced checkout to clear uncommitted changes
        sc = salt_control.SaltController(settings)
        rc = salt_control.RemoteCommands(sc)
        branch = gddoc['location']['default_branch']
        path = gddoc['location']['path']
        res = rc.discard_git_changes(servers, path)
        elita.util.debugLog("_threadsafe_process_gitdeploy", "discard git changes result: {}".format(str(res)))
        res = rc.checkout_branch(servers, path, branch)
        elita.util.debugLog("_threadsafe_process_gitdeploy", "git checkout result: {}".format(str(res)))

def _threadsafe_pull_callback(results, tag, **kwargs):
    '''
    Passed to run_slses_async and is used to provide realtime updates to users polling the deploy job object
    '''
    datasvc = kwargs['datasvc']
    datasvc.jobsvc.NewJobData({"DeployServers": {"results": results, "tag": tag}})

def _threadsafe_pull_gitdeploy(application, gitdeploy_struct, queue, settings, job_id):
    '''
    Thread-safe way of performing a deployment SLS call for one specific gitdeploy on a group of servers
    gitdeploy_struct: { "gitdeploy_name": [ list_of_servers_to_deploy_to ] }
    '''

    datasvc = elita.actions.action.regen_datasvc(settings, job_id)
    sc = salt_control.SaltController(settings)
    rc = salt_control.RemoteCommands(sc)

    assert len(gitdeploy_struct) == 1
    gd_name = gitdeploy_struct.keys()[0]
    servers = gitdeploy_struct[gd_name]

    #until salt Helium is released, we can only execute an SLS *file* as opposed to a single module call
    sls_map = {sc.get_gitdeploy_entry_name(application, gd_name): servers}
    if len(sls_map) == 0:
        datasvc.jobsvc.NewJobData({"DeployServers": {gd_name: "no servers"}})
        return True

    datasvc.jobsvc.NewJobData({"DeployServers": {gd_name: "deploying", "servers": servers}})
    elita.util.debugLog("_threadsafe_pull_gitdeploy", "sls_map: {}".format(sls_map))
    res = rc.run_slses_async(_threadsafe_pull_callback, sls_map, args={'datasvc': datasvc})
    elita.util.debugLog("_threadsafe_pull_gitdeploy", "results: {}".format(res))
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
        elita.util.debugLog("_threadsafe_pull_gitdeploy", "SLS error servers: {}".format(errors.keys()))
        elita.util.debugLog("_threadsafe_pull_gitdeploy", "SLS error responses: {}".format(errors))

    deploy_results = {
        gd_name: {
            "errors": len(errors) > 0,
            "error_results": errors,
            "successes": len(successes) > 0,
            "success_results": successes
        }
    }

    queue.put(deploy_results)

    datasvc.jobsvc.NewJobData({
        "DeployServers": deploy_results
    })

    return len(errors) == 0


class DeployController:

    def __init__(self, datasvc):
        self.datasvc = datasvc
        self.changed_gitdeploys = dict()

    # def add_to_changed_gitdeploys(self, gddoc):
    #     self.changed_gitdeploys[gddoc['name']] = list(set(gddoc['servers']).intersection(set(self.servers)))
    #
    # def push_to_gitdeploy(self, gdm, gddoc):
    #     self.add_msg("Starting push to gitdeploy: {}".format(gddoc['name']))
    #     package = gddoc['package']
    #     package_doc = self.build_doc['packages'][package]
    #     self.current_step += 1
    #     #self.add_msg("Checking out default git branch")
    #     res = gdm.checkout_default_branch()
    #     elita.util.debugLog(self, "git checkout output: {}".format(str(res)))
    #     self.current_step += 1
    #     if gdm.last_build == self.build_name:
    #         self.add_msg("Build already committed to local gitrepo; skipping package decompression")
    #         self.current_step += 5
    #     else:
    #         self.add_msg("Decompressing package to master gitdeploy repo")
    #         gdm.decompress_to_repo(package_doc)
    #         self.current_step += 1
    #         elita.util.debugLog(self, "Checking for changes")
    #         res = gdm.check_repo_status()
    #         elita.util.debugLog(self, "git status results: {}".format(str(res)))
    #
    #         if "nothing to commit" in res:
    #             self.current_step += 4
    #             self.add_msg("No changes to commit/push")
    #         else:
    #             self.current_step += 1
    #             self.add_msg("Adding changed files to commit")
    #             res = gdm.add_files_to_repo()
    #             elita.util.debugLog(self, "git add result: {}".format(str(res)))
    #             self.current_step += 1
    #             self.add_msg("Committing changes")
    #             res = gdm.commit_to_repo(self.build_name)
    #             elita.util.debugLog(self, "git commit result: {}".format(str(res)))
    #             self.current_step += 1
    #             res = gdm.inspect_latest_diff()
    #             elita.util.debugLog(self, "inspect diff result: {}".format(str(res)))
    #             self.current_step += 1
    #             self.add_msg("Pushing changes to git provider")
    #             res = gdm.push_repo()
    #             elita.util.debugLog(self, "git push result: {}".format(str(res)))
    #             # Changes detected, so add gitdeploy and the relevant servers that must be deployed to
    #             self.add_to_changed_gitdeploys(gddoc)
    #         gdm.update_repo_last_build(self.build_name)
    #     # in the event that the gitrepo hasn't changed, but the gitdeploy indicates that we haven't successfully
    #     # deployed to all servers, we want to force git pull
    #     # this can happen if multiple gitdeploys share the same gitrepo
    #     if gdm.stale:
    #         if gddoc['name'] not in self.changed_gitdeploys:
    #             self.add_to_changed_gitdeploys(gddoc)
    #     self.add_msg("Finished gitdeploy push")

    # def pull_callback(self, results, tag):
    #     self.add_msg("pull target: {} result: {}".format(tag, results))
    #
    # def get_gitdeploy_servers(self, gddoc):
    #     '''
    #     Filter self.servers to find only those with gitdeploy initialized on them
    #     '''
    #     return list(set(gddoc['servers']).intersection(set(self.servers)))
    #
    #
    # def git_pull_gitdeploys(self):
    #     #until salt Helium is released, we can only execute an SLS *file* as opposed to a single module call
    #     sls_map = {self.sc.get_gitdeploy_entry_name(self.application, gd): self.changed_gitdeploys[gd]
    #                for gd in self.changed_gitdeploys}
    #     if len(sls_map) == 0:
    #         self.add_msg("No servers to deploy to!")
    #         self.current_step += 2
    #         return True
    #     self.current_step += 1
    #     self.add_msg("Executing states and git pull: {}".format(self.servers))
    #     elita.util.debugLog(self, "git_pull_gitdeploys: sls_map: {}".format(sls_map))
    #     res = self.rc.run_slses_async(self.pull_callback, sls_map)
    #     elita.util.debugLog(self, "git_pull_gitdeploys: results: {}".format(res))
    #     errors = dict()
    #     successes = dict()
    #     for r in res:
    #         for host in r:
    #             for cmd in r[host]:
    #                 if "gitdeploy" in cmd:
    #                     if "result" in r[host][cmd]:
    #                         if not r[host][cmd]["result"]:
    #                             errors[host] = r[host][cmd]["changes"] if "changes" in r[host][cmd] else r[host][cmd]
    #                         else:
    #                             if host not in successes:
    #                                 successes[host] = dict()
    #                             module, state, command, subcommand = str(cmd).split('|')
    #                             if state not in successes[host]:
    #                                 successes[host][state] = dict()
    #                             successes[host][state][command] = {
    #                                 "stdout": r[host][cmd]["changes"]["stdout"],
    #                                 "stderr": r[host][cmd]["changes"]["stderr"],
    #                                 "retcode": r[host][cmd]["changes"]["retcode"],
    #                             }
    #     if len(errors) > 0:
    #         elita.util.debugLog(self, "SLS error servers: {}".format(errors.keys()))
    #         elita.util.debugLog(self, "SLS error responses: {}".format(errors))
    #         self.error_msg("Errors detected in sls execution on servers: {}".format(errors.keys()))
    #     elif len(successes) > 0:
    #         self.add_msg("Successful git pull and state execution")
    #     self.current_step += 1
    #     return len(errors) == 0

    def run(self, app_name, build_name, servers, gitdeploys, force=False):
        '''
        1. Decompress build to gitdeploy dir and push
            a. Iterate over server_specs to build list of gitdeploys to push to (make sure no dupes)
            b. Push desired build to gitdeploys
        2. Determine which gitdeploys have changes (if any)
            a. Build a mapping of gitdeploys_with_changes -> [ servers_to_deploy_it_to ]
            b. Perform the state calls
        '''
        build_doc = self.datasvc.buildsvc.GetBuildDoc(app_name, build_name)
        gitdeploy_docs = dict()
        #reset changed gitdeploys
        self.changed_gitdeploys = dict()

        queue = multiprocessing.Queue()
        procs = list()
        for gd in gitdeploys:
            gddoc = self.datasvc.gitsvc.GetGitDeploy(app_name, gd)
            gitdeploy_docs[gd] = gddoc
            p = multiprocessing.Process(target=_threadsafe_process_gitdeploy,
                                        args=(gddoc, build_doc, servers, queue, self.datasvc.settings,
                                              self.datasvc.job_id))
            p.start()
            procs.append(p)

            # if this is part of a rolling deployment and is anything other than the first batch,
            # no gitdeploys will actually be "changed". Force says to do a pull on the servers anyway.
            if force:
                elita.util.debugLog(self, "Force flag set, adding gitdeploy servers to deploy list: {}".format(gd))
                queue.put({gd: determine_deployabe_servers(gddoc['servers'], servers)})

        for p in procs:
            p.join(300)
            if p.is_alive():
                elita.util.debugLog(self, "ERROR: _threadsafe_process_gitdeploy: timeout waiting for child process!")

        while not queue.empty():
            gd = queue.get()
            for g in gd:
                self.changed_gitdeploys[g] = gd[g]

        queue = multiprocessing.Queue()
        procs = list()
        for gd in self.changed_gitdeploys:
            p = multiprocessing.Process(target=_threadsafe_pull_gitdeploy,
                                        args=(app_name, {gd: self.changed_gitdeploys[gd]}, queue, self.datasvc.settings,
                                              self.datasvc.job_id))
            p.start()
            procs.append(p)

        for p in procs:
            p.join(600)
            if p.is_alive():
                elita.util.debugLog(self, "ERROR: _threadsafe_pull_gitdeploy: timeout waiting for child process!")

        results = list()
        while not queue.empty():
            results.append(queue.get())

        for r in results:
            for gd in r:
                if r[gd]['errors']:
                    return False, results

        #update deployed_build
        for gd in gitdeploys:
            gdm = gitservice.GitDeployManager(gitdeploy_docs[gd], self.datasvc)
            gdm.update_last_deployed(build_name)

        return True, results

