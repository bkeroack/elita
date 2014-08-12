__author__ = 'bkeroack'

import sys
import logging
import traceback
import time
import billiard
import itertools
import pprint
pp = pprint.PrettyPrinter(indent=4)

import elita.util
import elita.util.type_check
import gitservice
import salt_control
from elita.actions.action import regen_datasvc

#async callable
def run_deploy(datasvc, application, build_name, target, rolling_divisor, rolling_pause, deployment_id):
    '''
    Asynchronous entry point for deployments
    '''

    # normally there's a higher level try/except block for all async actions
    # we want to make sure the error is saved in the deployment object as well, not just the job
    # so we duplicate the functionality here
    try:
        if target['groups']:
            logging.debug("run_deploy: Doing rolling deployment")
            dc = DeployController(datasvc, deployment_id)
            rdc = RollingDeployController(datasvc, dc, deployment_id)
            ret = rdc.run(application, build_name, target, rolling_divisor, rolling_pause)
        else:
            logging.debug("run_deploy: Doing manual deployment")
            dc = DeployController(datasvc, deployment_id)
            ret, data = dc.run(application, build_name, target['servers'], target['gitdeploys'])
    except:
        exc_type, exc_obj, tb = sys.exc_info()
        f_exc = traceback.format_exception(exc_type, exc_obj, tb)
        results = {
            "error": "unhandled exception during callable!",
            "exception": f_exc
        }
        logging.debug("run_deploy: EXCEPTION: {}".format(f_exc))
        datasvc.deploysvc.UpdateDeployment(application, deployment_id, {"status": "error"})
        return {"deploy_status": "error", "details": results}
    datasvc.deploysvc.CompleteDeployment(application, deployment_id)
    datasvc.deploysvc.UpdateDeployment(application, deployment_id, {"status": "complete" if ret else "error"})
    return {"deploy_status": "done" if ret else "error"}


class BatchCompute:
    '''
        Given a list of application groups that require rolling deployment and an (optional) list that do not,
        compute the optimal batches of server/gitdeploy pairs. All non-rolling groups are added to the first batch.
        Splitting algorithm is tolerant of outrageously large rolling_divisors.

        Written in a functional style to facilitate testing.
    '''

    @staticmethod
    def add_nonrolling_groups(batches, nonrolling_docs):
        '''
        Add servers and gitdeploys from nonrolling groups to the first batch
        Not written in a functional style because that was totally unreadable
        '''
        if nonrolling_docs and len(nonrolling_docs) > 0:
            assert len(batches) > 0
            assert all(map(lambda x: 'servers' in x and 'gitdeploys' in x, batches))
            assert all(map(lambda x: 'servers' in x[1] and 'gitdeploys' in x[1], nonrolling_docs.iteritems()))
            for g in nonrolling_docs:
                for k in ('servers', 'gitdeploys'):
                    batches[0][k] += nonrolling_docs[g][k]
        return batches

    @staticmethod
    def dedupe_batches(batches):
        '''
        Dedupe servers and gitdeploys list in the combined batches list:
        [
            { "servers": [ "server1", "server1", ...], "gitdeploys": [ "gd1", "gd1", ...] },  #batch 0 (all groups)
            { "servers": [ "server1", "server1", ...], "gitdeploys": [ "gd1", "gd1", ...] },  #batch 1 (all groups)
            ...
        ]
        '''
        assert len(batches) > 0
        assert all(map(lambda x: 'servers' in x and 'gitdeploys' in x, batches))
        return map(lambda x: {"servers": list(set(x['servers'])), "gitdeploys": list(set(elita.util.flatten_list(x['gitdeploys'])))}, batches)

    @staticmethod
    def reduce_group_batches(accumulated, update):
        assert 'servers' in accumulated and 'servers' in update
        assert 'gitdeploys' in accumulated and 'gitdeploys' in update
        return {
            "servers": accumulated['servers'] + update['servers'],
            "gitdeploys": accumulated['gitdeploys'] + update['gitdeploys']
        }

    @staticmethod
    def coalesce_batches(batches):
        '''
        Combine the big list of batches into a single list.

        Function is passed a list of lists:
        [
            [ { "servers": [...], "gitdeploys": [...] }, ... ],     # batches 0-n for group A
            [ { "servers": [...], "gitdeploys": [...] }, ... ],     # batches 0-n for broup B
            ...
        ]

        Each nested list represents the computed batches for an individual group. All nested lists are expected to be
        the same length.
        '''
        assert len(batches) > 0
        #assert all(map(lambda x: len(x) == len(batches[0]), batches))  # all batches must be the same length

        return map(
            lambda batch_aggregate: reduce(
                lambda acc, upd:
                {
                    'servers': acc['servers'] + upd['servers'],
                    'gitdeploys': acc['gitdeploys'] + upd['gitdeploys']
                }, batch_aggregate
            ), itertools.izip_longest(*batches, fillvalue={"servers": [], "gitdeploys": []}))

    @staticmethod
    def compute_group_batches(divisor, group):
        '''
        Compute batches for group.
        Group is iteritems() result from group dict. group[0] is key (name), group[1] is dict of servers/gitdeploys

        return list of dicts: [ { 'servers': [...], 'gitdeploys': [...] }, ... ]
        '''
        assert len(group) == 2
        assert 'servers' in group[1]
        assert 'gitdeploys' in group[1]

        servers = group[1]['servers']
        gitdeploys = group[1]['gitdeploys']
        server_batches = elita.util.split_seq(servers, divisor)
        gd_multiplier = len(server_batches)  # gitdeploy_batches multipler
        if isinstance(gitdeploys[0], list):
            # duplicate all server batches by the length of the gitdeploy list-of-lists
            server_batches = [x for item in server_batches for x in itertools.repeat(item, len(gitdeploys))]
            gitdeploy_batches = list(gitdeploys) * gd_multiplier
        else:
            gitdeploy_batches = [gitdeploys] * gd_multiplier
        assert len(gitdeploy_batches) == len(server_batches)
        return [{'servers': sb, 'gitdeploys': gd} for sb, gd in zip(server_batches, gitdeploy_batches)]

    @staticmethod
    def compute_rolling_batches(divisor, rolling_group_docs, nonrolling_group_docs):
        assert isinstance(divisor, int)
        assert len(rolling_group_docs) > 0
        assert elita.util.type_check.is_dictlike(rolling_group_docs)
        assert all(map(lambda x: 'servers' in x[1] and 'gitdeploys' in x[1], rolling_group_docs.iteritems()))
        return BatchCompute.dedupe_batches(
            BatchCompute.add_nonrolling_groups(
                BatchCompute.coalesce_batches(
                    map(lambda x: BatchCompute.compute_group_batches(divisor, x), rolling_group_docs.iteritems())
                ), nonrolling_group_docs
            )
        )


class RollingDeployController:
    '''
    Break deployment up into server/gitdeploy batches, then invoke DeployController with each batch sequentially
    '''
    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, datasvc, deploy_controller, deployment_id):
        '''
        @type datasvc: models.DataService
        '''
        self.datasvc = datasvc
        self.dc = deploy_controller
        self.deployment_id = deployment_id

    def get_nonrolling_groups(self, rolling_groups, all_groups):
        return list(set(all_groups) - set(rolling_groups))

    def compute_batches(self, rolling_group_docs, nonrolling_group_docs, rolling_divisor):
        return BatchCompute.compute_rolling_batches(rolling_divisor, rolling_group_docs, nonrolling_group_docs)

    def run(self, application, build_name, target, rolling_divisor, rolling_pause, parallel=True):
        '''
        Run rolling deployment. This should be called iff the deployment is called via groups/environments
        '''

        groups = target['groups']
        rolling_groups = [g for g in groups if self.datasvc.groupsvc.GetGroup(application, g)['rolling_deploy']]
        rolling_group_docs = {g: self.datasvc.groupsvc.GetGroup(application, g) for g in rolling_groups}
        nonrolling_groups = self.get_nonrolling_groups(rolling_groups, groups)
        nonrolling_group_docs = {g: self.datasvc.groupsvc.GetGroup(application, g) for g in nonrolling_groups}

        if len(rolling_groups) > 0:
            batches = self.compute_batches(rolling_group_docs, nonrolling_group_docs, rolling_divisor)

            logging.debug("computed batches: {}".format(batches))

            self.datasvc.deploysvc.InitializeDeploymentPlan(application, self.deployment_id, batches, target['gitdeploys'])

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
                logging.debug("doing DeployController.run: deploy_gds: {}".format(deploy_gds))
                ok, results = self.dc.run(application, build_name, b['servers'], deploy_gds, force=i > 0, parallel=parallel)
                changed_gds = self.dc.changed_gitdeploys.keys()
                if not ok:
                    self.datasvc.jobsvc.NewJobData({"RollingDeployment": "error"})
                    return False

                if i != (len(batches)-1):
                    time.sleep(rolling_pause)

        else:

            self.datasvc.deploysvc.update_deployment_plan(application, self.deployment_id,
                                        [{'gitdeploys': target['gitdeploys'], 'servers': target['servers']}],
                                        target['gitdeploys'])

            self.datasvc.jobsvc.NewJobData({
                "RollingDeployment": {
                    "batches": 1,
                    "batch_data": [{"servers": target['servers'], "gitdeploys": target["gitdeploys"]}]
                }
            })

            ok, results = self.dc.run(application, build_name, target['servers'], target['gitdeploys'], parallel=parallel)
            if not ok:
                self.datasvc.jobsvc.NewJobData({"RollingDeployment": "error"})
                return False

        return True

def determine_deployabe_servers(all_gd_servers, specified_servers):
    return list(set(all_gd_servers).intersection(set(specified_servers)))

def _threadsafe_process_gitdeploy(gddoc, build_doc, servers, queue, settings, job_id, deployment_id):
    '''
    Threadsafe function for processing a single gitdeploy during a deployment.
    Creates own instance of datasvc, etc.
    Pushes changed gitdeploys to a shared queue
    '''

    package = gddoc['package']
    package_doc = build_doc['packages'][package]
    changed = False

    client, datasvc = regen_datasvc(settings, job_id)
    gdm = gitservice.GitDeployManager(gddoc, datasvc)

    datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                              progress=10,
                                              step='Checking out default branch')

    try:
        res = gdm.checkout_default_branch()
    except:
        exc_msg = str(sys.exc_info()[1]).split('\n')
        exc_msg.insert(0, "ERROR: checkout_default_branch")
        datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                                  step=exc_msg)
        return

    logging.debug("_threadsafe_process_gitdeploy: git checkout output: {}".format(str(res)))

    if gdm.last_build == build_doc['build_name']:
        datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "already processed"}})
        datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                              progress=100,
                                              step='Complete (already processed)')
    else:
        datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                              progress=25,
                                              step='Decompressing package to repository')

        datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "processing"}})

        try:
            gdm.decompress_to_repo(package_doc)
        except:
            exc_msg = str(sys.exc_info()[1]).split('\n')
            exc_msg.insert(0, "ERROR: decompress_to_repo")
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                                      step=exc_msg)
            return

        datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                              progress=50,
                                              step='Checking for changes')

        logging.debug("_threadsafe_process_gitdeploy: Checking for changes")
        try:
            res = gdm.check_repo_status()
        except:
            exc_msg = str(sys.exc_info()[1]).split('\n')
            exc_msg.insert(0, "ERROR: check_repo_status")
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                                      step=exc_msg)
            return
        logging.debug("_threadsafe_process_gitdeploy: git status results: {}".format(str(res)))

        if "nothing to commit" in res:
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                              progress=100,
                                              step='Complete (no changes found)')
            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "no changes"}})
        else:
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                              progress=60,
                                              step='Adding changes to repository')
            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "adding to repository"}})
            try:
                res = gdm.add_files_to_repo()
            except:
                exc_msg = str(sys.exc_info()[1]).split('\n')
                exc_msg.insert(0, "ERROR: add_files_to_repo")
                datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                                          step=exc_msg)
                return
            logging.debug("_threadsafe_process_gitdeploy: git add result: {}".format(str(res)))

            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                              progress=70,
                                              step='Committing changes to repository')
            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "committing"}})
            try:
                res = gdm.commit_to_repo(build_doc['build_name'])
            except:
                exc_msg = str(sys.exc_info()[1]).split('\n')
                exc_msg.insert(0, "ERROR: commit_to_repo")
                datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                                          step=exc_msg)
                return
            logging.debug("_threadsafe_process_gitdeploy: git commit result: {}".format(str(res)))

            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "checking diff"}})
            try:
                res = gdm.inspect_latest_diff()
            except:
                exc_msg = str(sys.exc_info()[1]).split('\n')
                exc_msg.insert(0, "ERROR: inspect_latest_diff")
                datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                                          step=exc_msg)
                return
            logging.debug("_threadsafe_process_gitdeploy: inspect diff result: {}".format(str(res)))

            # change to a list of dicts without filenames as keys to keep mongo happy
            changed_files = [{
                'filename': k,
                'deletions': res[k]['deletions'],
                'lines': res[k]['lines'],
                'insertions': res[k]['insertions']
            } for k in res]

            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                              changed_files=changed_files)

            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                              progress=90,
                                              step='Pushing changes to gitprovider')
            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "pushing"}})
            try:
                res = gdm.push_repo()
            except:
                exc_msg = str(sys.exc_info()[1]).split('\n')
                exc_msg.insert(0, "ERROR: push_repo")
                datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                                          step=exc_msg)
                return
            logging.debug("_threadsafe_process_gitdeploy: git push result: {}".format(str(res)))
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                              progress=100,
                                              step='Complete')
            # Changes detected, so add gitdeploy and the relevant servers that must be deployed to
            changed = True
        try:
            gdm.update_repo_last_build(build_doc['build_name'])
        except:
            exc_msg = str(sys.exc_info()[1]).split('\n')
            exc_msg.insert(0, "ERROR: update_repo_last_build")
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gddoc['name'],
                                                      step=exc_msg)
            return
    # in the event that the gitrepo hasn't changed, but the gitdeploy indicates that we haven't successfully
    # deployed to all servers, we want to force git pull
    # this can happen if multiple gitdeploys share the same gitrepo
    if gdm.stale:
        changed = True

    if changed:
        queue.put({gddoc['name']: determine_deployabe_servers(gddoc['servers'], servers)})

def _threadsafe_pull_callback(results, tag, **kwargs):
    '''
    Passed to run_slses_async and is used to provide realtime updates to users polling the deploy job object
    '''
    datasvc = kwargs['datasvc']
    app = kwargs['application']
    deployment_id = kwargs['deployment_id']
    batch_number = kwargs['batch_number']
    gitdeploy = kwargs['gitdeploy']
    datasvc.jobsvc.NewJobData({"DeployServers": {"results": results, "tag": tag}})
    for r in results:
        #callback results always have a 'ret' key but underneath it may be a simple string or a big complex object
        #for state call results. We have to unpack the state results if necessary
        this_result = results[r]['ret']
        datasvc.jobsvc.NewJobData(this_result)
        if elita.util.type_check.is_dictlike(this_result):  # state result
            assert len(this_result.keys()) == 1
            top_key = this_result.keys()[0]
            assert top_key[:3] == 'cmd'
            assert elita.util.type_check.is_dictlike(this_result[top_key])
            assert all([k in this_result[top_key] for k in ("name", "result", "changes")])
            assert elita.util.type_check.is_dictlike(this_result[top_key]["changes"])
            assert "retcode" in this_result[top_key]["changes"]
            if this_result[top_key]["changes"]["retcode"] > 0 or not this_result[top_key]["result"]:
                state = ["ERROR: state failed"]
                state.append(this_result[top_key]["name"])
                state.append("return code: {}".format(this_result[top_key]["changes"]["retcode"]))
                for output in ("stderr", "stdout"):
                    if output in this_result[top_key]["changes"]:
                        state.append("{}:".format(output))
                        for l in str(this_result[top_key]["changes"][output]).split('\n'):
                            state.append(l)
                datasvc.jobsvc.NewJobData({'status': 'error', 'message': 'failing deployment due to detected error'})
                datasvc.deploysvc.UpdateDeployment_Phase2(app, deployment_id, gitdeploy, [r], batch_number,
                                                          state=state)
                datasvc.deploysvc.FailDeployment(app, deployment_id)
                return
            datasvc.deploysvc.UpdateDeployment_Phase2(app, deployment_id, gitdeploy, [r], batch_number,
                                                      state='Returned: {}'.format(this_result[top_key]["name"]),
                                                      progress=66)
        else:   # simple result
            datasvc.deploysvc.UpdateDeployment_Phase2(app, deployment_id, gitdeploy, [r], batch_number,
                                                      state=results[r]['ret'])

def _threadsafe_pull_gitdeploy(application, gitdeploy_struct, queue, settings, job_id, deployment_id, batch_number):
    '''
    Thread-safe way of performing a deployment SLS call for one specific gitdeploy on a group of servers
    gitdeploy_struct: { "gitdeploy_name": [ list_of_servers_to_deploy_to ] }
    '''
    assert application and gitdeploy_struct and queue and settings and job_id and deployment_id
    assert all([elita.util.type_check.is_string(gd) for gd in gitdeploy_struct])
    assert all([elita.util.type_check.is_seq(gitdeploy_struct[gd]) for gd in gitdeploy_struct])
    assert isinstance(batch_number, int) and batch_number >= 0

    client, datasvc = regen_datasvc(settings, job_id)
    sc = salt_control.SaltController(datasvc)
    rc = salt_control.RemoteCommands(sc)

    assert len(gitdeploy_struct) == 1
    gd_name = gitdeploy_struct.keys()[0]
    servers = gitdeploy_struct[gd_name]

    datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, servers, batch_number,
                                              progress=10,
                                              state="Beginning deployment")

    #until salt Helium is released, we can only execute an SLS *file* as opposed to a single module call
    sls_map = {sc.get_gitdeploy_entry_name(application, gd_name): servers}
    if len(servers) == 0:
        datasvc.jobsvc.NewJobData({"DeployServers": {gd_name: "no servers"}})
        return True

    #clear uncommitted changes on targets
    datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, servers, batch_number,
                                              progress=33,
                                              state="Clearing uncommitted changes")
    gd_doc = datasvc.gitsvc.GetGitDeploy(application, gd_name)
    branch = gd_doc['location']['default_branch']
    path = gd_doc['location']['path']
    res = rc.discard_git_changes(servers, path)
    logging.debug("_threadsafe_process_gitdeploy: discard git changes result: {}".format(str(res)))
    res = rc.checkout_branch(servers, path, branch)
    logging.debug("_threadsafe_process_gitdeploy: git checkout result: {}".format(str(res)))

    datasvc.jobsvc.NewJobData({"DeployServers": {gd_name: "deploying", "servers": servers}})
    logging.debug("_threadsafe_pull_gitdeploy: sls_map: {}".format(sls_map))

    datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, servers, batch_number,
                                              progress=50,
                                              state="Issuing state commands (git pull, etc)")
    res = rc.run_slses_async(_threadsafe_pull_callback, sls_map, args={'datasvc': datasvc, 'application': application,
                                                                       'deployment_id': deployment_id,
                                                                       'batch_number': batch_number,
                                                                       'gitdeploy': gd_name})
    logging.debug("_threadsafe_pull_gitdeploy: results: {}".format(res))
    errors = dict()
    successes = dict()
    for r in res:
        for host in r:
            for cmd in r[host]['ret']:
                if "gitdeploy" in cmd:
                    if "result" in r[host]['ret'][cmd]:
                        if not r[host]['ret'][cmd]["result"]:
                            errors[host] = r[host]['ret'][cmd]["changes"] if "changes" in r[host]['ret'][cmd] else r[host]['ret'][cmd]
                        else:
                            if host not in successes:
                                successes[host] = dict()
                            module, state, command, subcommand = str(cmd).split('|')
                            if state not in successes[host]:
                                successes[host][state] = dict()
                            successes[host][state][command] = {
                                "stdout": r[host]['ret'][cmd]["changes"]["stdout"],
                                "stderr": r[host]['ret'][cmd]["changes"]["stderr"],
                                "retcode": r[host]['ret'][cmd]["changes"]["retcode"],
                            }
    if len(errors) > 0:
        for e in errors:
            datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, [e], batch_number,
                                              state="ERROR: stderr: {}; stdout: {}; retcode: {}".format(
                                                  errors[e]["changes"]["stderr"],
                                                  errors[e]["changes"]["stdout"],
                                                  errors[e]["changes"]["retcode"]
                                              ))
        logging.debug("_threadsafe_pull_gitdeploy: SLS error servers: {}".format(errors.keys()))
        logging.debug("_threadsafe_pull_gitdeploy: SLS error responses: {}".format(errors))

    if len(successes) > 0:
        datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, successes.keys(), batch_number,
                                                  progress=100, state="Complete")

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
    '''
    Class that runs deploys. Only knows about server/gitdeploy pairs, so is used for both manual-style deployments
    and group/environment deployments.
    '''

    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, datasvc, deployment_id):
        self.deployment_id = deployment_id
        self.datasvc = datasvc
        self.changed_gitdeploys = dict()

    def run(self, app_name, build_name, servers, gitdeploys, force=False, parallel=True, batch_number=0):
        '''
        1. Decompress build to gitdeploy dir and push
            a. Attempts to optimize by determining if build has already been decompressed to gitdeploy and skips if so
        2. Determine which gitdeploys have changes (if any)
            a. Build a mapping of gitdeploys_with_changes -> [ servers_to_deploy_it_to ]
            b. Perform the state calls only to the server/gitdeploy pairs that have changes

        @type app_name: str
        @type build_name: str
        @type servers: list(str)
        @type gitdeploys: list(str)
        '''
        assert app_name and build_name and servers and gitdeploys
        assert elita.util.type_check.is_string(app_name)
        assert elita.util.type_check.is_string(build_name)
        assert elita.util.type_check.is_seq(servers)
        assert elita.util.type_check.is_seq(gitdeploys)
        assert isinstance(batch_number, int) and batch_number >= 0

        build_doc = self.datasvc.buildsvc.GetBuildDoc(app_name, build_name)
        gitdeploy_docs = dict()
        #reset changed gitdeploys
        self.changed_gitdeploys = dict()

        queue = billiard.Queue()
        procs = list()

        self.datasvc.deploysvc.StartDeployment_Phase(app_name, self.deployment_id, 1)
        for gd in gitdeploys:
            gddoc = self.datasvc.gitsvc.GetGitDeploy(app_name, gd)
            gitdeploy_docs[gd] = gddoc
            if parallel:
                p = billiard.Process(target=_threadsafe_process_gitdeploy,
                                            args=(gddoc, build_doc, servers, queue, self.datasvc.settings,
                                                  self.datasvc.job_id, self.deployment_id))
                p.start()
                procs.append(p)

            else:
                _threadsafe_process_gitdeploy(gddoc, build_doc, servers, queue, self.datasvc.settings,
                                              self.datasvc.job_id, self.deployment_id)

            # if this is part of a rolling deployment and is anything other than the first batch,
            # no gitdeploys will actually be "changed". Force says to do a pull on the servers anyway.
            if force:
                logging.debug("Force flag set, adding gitdeploy servers to deploy list: {}".format(gd))
                queue.put({gd: determine_deployabe_servers(gddoc['servers'], servers)})

        if parallel:
            for p in procs:
                p.join(300)
                if p.is_alive():
                    logging.debug("ERROR: _threadsafe_process_gitdeploy: timeout waiting for child process!")

        while not queue.empty():
            gd = queue.get(block=False)
            for g in gd:
                self.changed_gitdeploys[g] = gd[g]

        queue = billiard.Queue()
        procs = list()
        self.datasvc.deploysvc.StartDeployment_Phase(app_name, self.deployment_id, 2)
        for gd in self.changed_gitdeploys:
            if parallel:
                p = billiard.Process(target=_threadsafe_pull_gitdeploy,
                                            args=(app_name, {gd: self.changed_gitdeploys[gd]}, queue, self.datasvc.settings,
                                                  self.datasvc.job_id, self.deployment_id, batch_number))
                p.start()
                procs.append(p)
            else:
                _threadsafe_pull_gitdeploy(app_name, {gd: self.changed_gitdeploys[gd]}, queue, self.datasvc.settings,
                                           self.datasvc.job_id, self.deployment_id, batch_number)
        if parallel:
            for p in procs:
                p.join(600)
                if p.is_alive():
                    logging.debug("ERROR: _threadsafe_pull_gitdeploy: timeout waiting for child process!")

        results = list()
        while not queue.empty():
            results.append(queue.get(block=False))

        for r in results:
            for gd in r:
                if r[gd]['errors']:
                    return False, results

        #update deployed_build
        for gd in gitdeploys:
            gdm = gitservice.GitDeployManager(gitdeploy_docs[gd], self.datasvc)
            gdm.update_last_deployed(build_name)

        return True, results

