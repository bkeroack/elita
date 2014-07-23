__author__ = 'bkeroack'

import sys
import logging
import traceback
import time
import multiprocessing
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
        return map(lambda x: {"servers": list(set(x['servers'])), "gitdeploys": list(set(x['gitdeploys']))}, batches)

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
        assert isinstance(rolling_group_docs, dict)
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

    def update_deployment_plan(self, app, batches, gitdeploys):
        '''
        Update deployment object with deployment plan (batches, etc) which can then be filled in with progress
        information as the deployment progresses
        '''
        assert app and batches and gitdeploys
        assert isinstance(app, str)
        assert elita.util.type_check.is_dictlike(batches)
        assert elita.util.type_check.is_seq(gitdeploys)

        for gd in gitdeploys:
            doc = {
                'progress': {
                    'phase1': {
                        'gitdeploys': {
                            gd: {
                                'progress': 0,
                                'step': 'not started',
                                'changed_files': []
                            }
                        }
                    }
                }
            }
            self.datasvc.deploysvc.UpdateDeployment(app, self.deployment_id, doc)

        gitdeploy_docs = {gd: self.datasvc.groupsvc.GetGroup(app, gd) for gd in gitdeploys}

        # at a low level, deployment operates in a gitdeploy-centric way
        # but on a human level, a server-centric view is more intuitive, so we generate a list of servers per batch,
        # then the gitdeploys to be deployed on each server:
        # batch 0:
        #   server0:
        #       - gitdeployA
        #           * path: C:\foo\bar
        #           * package: webapplication
        #           * progress: 0%
        #           * state: not started
        #       - gitdeployB
        #           * progress: 10%
        #           * package: webapplication
        #           * progress: 0%
        #           * state: checking out default branch


        doc = {
            'progress': {
                'phase2': {}
            }
        }
        for i, batch in enumerate(batches):
            doc['progress']['phase2'][i] = {}
            for server in batch['servers']:
                doc['progress']['phase2'][i][server] = {}
                for gitdeploy in batch['gitdeploys']:
                    if server in determine_deployabe_servers(gitdeploy_docs[gitdeploy], [server]):
                        doc['progress']['phase2'][i][server][gitdeploy] = {
                            'path': gitdeploy_docs[gitdeploy]['location']['path'],
                            'package': gitdeploy_docs[gitdeploy]['location']['package'],
                            'progress': 0,
                            'state': 'not started'
                        }

        self.datasvc.deploysvc.UpdateDeployment(app, self.deployment_id, doc)


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

def _threadsafe_process_gitdeploy(gddoc, build_doc, servers, queue, settings, job_id):
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

    res = gdm.checkout_default_branch()
    logging.debug("_threadsafe_process_gitdeploy: git checkout output: {}".format(str(res)))

    if gdm.last_build == build_doc['build_name']:
        datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "already processed"}})
    else:

        datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "processing"}})
        gdm.decompress_to_repo(package_doc)

        logging.debug("_threadsafe_process_gitdeploy: Checking for changes")
        res = gdm.check_repo_status()
        logging.debug("_threadsafe_process_gitdeploy: git status results: {}".format(str(res)))

        if "nothing to commit" in res:
            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "no changes"}})
        else:

            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "adding to repository"}})
            res = gdm.add_files_to_repo()
            logging.debug("_threadsafe_process_gitdeploy: git add result: {}".format(str(res)))

            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "committing"}})
            res = gdm.commit_to_repo(build_doc['build_name'])
            logging.debug("_threadsafe_process_gitdeploy: git commit result: {}".format(str(res)))

            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "checking diff"}})
            res = gdm.inspect_latest_diff()
            logging.debug("_threadsafe_process_gitdeploy: inspect diff result: {}".format(str(res)))

            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "pushing"}})
            res = gdm.push_repo()
            logging.debug("_threadsafe_process_gitdeploy: git push result: {}".format(str(res)))
            # Changes detected, so add gitdeploy and the relevant servers that must be deployed to
            changed = True
        gdm.update_repo_last_build(build_doc['build_name'])
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
        logging.debug("_threadsafe_process_gitdeploy: discard git changes result: {}".format(str(res)))
        res = rc.checkout_branch(servers, path, branch)
        logging.debug("_threadsafe_process_gitdeploy: git checkout result: {}".format(str(res)))

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

    client, datasvc = regen_datasvc(settings, job_id)
    sc = salt_control.SaltController(settings)
    rc = salt_control.RemoteCommands(sc)

    assert len(gitdeploy_struct) == 1
    gd_name = gitdeploy_struct.keys()[0]
    servers = gitdeploy_struct[gd_name]

    #until salt Helium is released, we can only execute an SLS *file* as opposed to a single module call
    sls_map = {sc.get_gitdeploy_entry_name(application, gd_name): servers}
    if len(servers) == 0:
        datasvc.jobsvc.NewJobData({"DeployServers": {gd_name: "no servers"}})
        return True

    datasvc.jobsvc.NewJobData({"DeployServers": {gd_name: "deploying", "servers": servers}})
    logging.debug("_threadsafe_pull_gitdeploy: sls_map: {}".format(sls_map))
    res = rc.run_slses_async(_threadsafe_pull_callback, sls_map, args={'datasvc': datasvc})
    logging.debug("_threadsafe_pull_gitdeploy: results: {}".format(res))
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
        logging.debug("_threadsafe_pull_gitdeploy: SLS error servers: {}".format(errors.keys()))
        logging.debug("_threadsafe_pull_gitdeploy: SLS error responses: {}".format(errors))

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
        assert isinstance(app_name, str)
        assert isinstance(build_name, str)
        assert elita.util.type_check.is_seq(servers)
        assert elita.util.type_check.is_seq(gitdeploys)
        assert isinstance(batch_number, int) and batch_number >= 0

        build_doc = self.datasvc.buildsvc.GetBuildDoc(app_name, build_name)
        gitdeploy_docs = dict()
        #reset changed gitdeploys
        self.changed_gitdeploys = dict()

        queue = multiprocessing.Queue()
        procs = list()
        for gd in gitdeploys:
            gddoc = self.datasvc.gitsvc.GetGitDeploy(app_name, gd)
            gitdeploy_docs[gd] = gddoc
            if parallel:
                p = multiprocessing.Process(target=_threadsafe_process_gitdeploy,
                                            args=(gddoc, build_doc, servers, queue, self.datasvc.settings,
                                                  self.datasvc.job_id))
                p.start()
                procs.append(p)

            else:
                _threadsafe_process_gitdeploy(gddoc, build_doc, servers, queue, self.datasvc.settings,
                                              self.datasvc.job_id)

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

        queue = multiprocessing.Queue()
        procs = list()
        for gd in self.changed_gitdeploys:
            if parallel:
                p = multiprocessing.Process(target=_threadsafe_pull_gitdeploy,
                                            args=(app_name, {gd: self.changed_gitdeploys[gd]}, queue, self.datasvc.settings,
                                                  self.datasvc.job_id))
                p.start()
                procs.append(p)
            else:
                _threadsafe_pull_gitdeploy(app_name, {gd: self.changed_gitdeploys[gd]}, queue, self.datasvc.settings,
                                           self.datasvc.job_id)
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

