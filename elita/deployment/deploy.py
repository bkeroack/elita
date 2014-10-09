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

class FatalDeploymentError(Exception):
    pass

#async callable
def run_deploy(datasvc, application, build_name, target, rolling_divisor, rolling_pause, ordered_pause, deployment_id):
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
            ret = rdc.run(application, build_name, target, rolling_divisor, rolling_pause, ordered_pause)
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
            assert all(map(lambda x: 'servers' in x and 'gitdeploys' in x, batches)) or not batches
            assert all(map(lambda x: 'servers' in x[1] and 'gitdeploys' in x[1], nonrolling_docs.iteritems()))
            non_rolling_batches = list()
            for g in nonrolling_docs:
                servers = nonrolling_docs[g]['servers']
                gitdeploys = nonrolling_docs[g]['gitdeploys']
                ordered = isinstance(nonrolling_docs[g]['gitdeploys'][0], list)
                if ordered:
                    for i, gdb in enumerate(nonrolling_docs[g]['gitdeploys']):
                        if i > len(non_rolling_batches)-1:
                            non_rolling_batches.append({'gitdeploys': gdb, 'servers': servers})
                        else:
                            non_rolling_batches[i]['servers'] = list(set(servers + non_rolling_batches[i]['servers']))
                            non_rolling_batches[i]['gitdeploys'] = list(set(gdb + non_rolling_batches[i]['gitdeploys']))
                        if i == len(nonrolling_docs[g]['gitdeploys'])-1:
                            non_rolling_batches[i]['ordered_gitdeploy'] = False
                        else:
                            non_rolling_batches[i]['ordered_gitdeploy'] = True
                else:
                    non_rolling_batches.append({'gitdeploys': gitdeploys, 'servers': servers, 'ordered_gitdeploy': False})
            for i, nrb in enumerate(non_rolling_batches):
                if i > len(batches)-1:
                    batches.append(nrb)
                else:
                    batches[i]['servers'] = list(set(nrb['servers'] + batches[i]['servers']))
                    batches[i]['gitdeploys'] = list(set(nrb['gitdeploys'] + batches[i]['gitdeploys']))
                    batches[i]['ordered_gitdeploy'] = nrb['ordered_gitdeploy']
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
        return map(lambda x: {"servers": list(set(x['servers'])),
                              "gitdeploys": list(set(elita.util.flatten_list(x['gitdeploys']))),
                              "ordered_gitdeploy": x['ordered_gitdeploy']}, batches)

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
        if not batches:
            return list()

        return map(
            lambda batch_aggregate: reduce(
                lambda acc, upd:
                {
                    'servers': acc['servers'] + upd['servers'],
                    'gitdeploys': acc['gitdeploys'] + upd['gitdeploys'],
                    'ordered_gitdeploy': acc['ordered_gitdeploy'] and upd['ordered_gitdeploy']
                }, batch_aggregate
            ), itertools.izip_longest(*batches, fillvalue={"servers": [], "gitdeploys": [], "ordered_gitdeploy": False}))

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
        ordered = isinstance(gitdeploys[0], list)
        if ordered:
            # duplicate all server batches by the length of the gitdeploy list-of-lists
            server_batches = [x for item in server_batches for x in itertools.repeat(item, len(gitdeploys))]
            gitdeploy_batches = list(gitdeploys) * gd_multiplier
            ordered_flags = [True] * (len(gitdeploys) - 1)
            ordered_flags.append(False)
            ordered_flags = ordered_flags * gd_multiplier
        else:
            gitdeploy_batches = [gitdeploys] * gd_multiplier
            ordered_flags = [False] * gd_multiplier
        assert len(gitdeploy_batches) == len(server_batches)
        batches = [{'servers': sb, 'gitdeploys': gd, 'ordered_gitdeploy': of}
                   for sb, gd, of in zip(server_batches, gitdeploy_batches, ordered_flags)]
        return batches


    @staticmethod
    def compute_rolling_batches(divisor, rolling_group_docs, nonrolling_group_docs):
        assert isinstance(divisor, int)
        assert elita.util.type_check.is_optional_dict(rolling_group_docs)
        assert not rolling_group_docs or all(map(lambda x: 'servers' in x[1] and 'gitdeploys' in x[1], rolling_group_docs.iteritems()))
        return BatchCompute.dedupe_batches(
            BatchCompute.add_nonrolling_groups(
                BatchCompute.coalesce_batches(
                    map(lambda x: BatchCompute.compute_group_batches(divisor, x), rolling_group_docs.iteritems() if rolling_group_docs else tuple())
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

    def run_hook(self, name, application, build_name, batches, batch_number=None, target=None):
        args = {
            "hook_parameters": {
                "deployment_id": self.deployment_id,
                "build": build_name
            }
        }

        if name == "AUTO_DEPLOYMENT_START":
            args['hook_parameters']['target'] = target
            args['hook_parameters']['batches'] = batches
        if name == "AUTO_DEPLOYMENT_COMPLETE" or name == "AUTO_DEPLOYMENT_FAILED":
            args['hook_parameters']['deployment'] = self.datasvc.deploysvc.GetDeployment(application,
                                                                                         self.deployment_id)
            args['hook_parameters']['batches'] = batches
        if "AUTO_DEPLOYMENT_BATCH" in name:
            args['hook_parameters']['batch_number'] = batch_number
            args['hook_parameters']['batch_count'] = len(batches)
            args['hook_parameters']['batch'] = batches[batch_number]
        self.datasvc.actionsvc.hooks.run_hook(application, name, args)

    def run(self, application, build_name, target, rolling_divisor, rolling_pause, ordered_pause, parallel=True):
        '''
        Run rolling deployment. This should be called iff the deployment is called via groups/environments
        '''

        groups = target['groups']
        rolling_groups = [g for g in groups if self.datasvc.groupsvc.GetGroup(application, g)['rolling_deploy']]
        rolling_group_docs = {g: self.datasvc.groupsvc.GetGroup(application, g) for g in rolling_groups}
        nonrolling_groups = self.get_nonrolling_groups(rolling_groups, groups)
        nonrolling_group_docs = {g: self.datasvc.groupsvc.GetGroup(application, g) for g in nonrolling_groups}

        gd_docs = [self.datasvc.gitsvc.GetGitDeploy(application, gd) for gd in target['gitdeploys']]
        gitrepos = [gd['location']['gitrepo']['name'] for gd in gd_docs]

        batches = self.compute_batches(rolling_group_docs, nonrolling_group_docs, rolling_divisor)

        logging.debug("computed batches: {}".format(batches))

        #run pre hook
        self.run_hook("AUTO_DEPLOYMENT_START", application, build_name, batches, target=target)

        self.datasvc.deploysvc.InitializeDeploymentPlan(application, self.deployment_id, batches, gitrepos)

        self.datasvc.jobsvc.NewJobData({
            "RollingDeployment": {
                "batches": len(batches),
                "batch_data": batches
            }
        })

        for i, b in enumerate(batches):
            logging.debug("doing DeployController.run: deploy_gds: {}".format(b['gitdeploys']))

            #run start hook
            self.run_hook("AUTO_DEPLOYMENT_BATCH_BEGIN", application, build_name, batches, batch_number=i)

            ok, results = self.dc.run(application, build_name, b['servers'], b['gitdeploys'],
                                      parallel=parallel, batch_number=i)
            if not ok:
                self.datasvc.jobsvc.NewJobData({"RollingDeployment": "error"})
                self.run_hook("AUTO_DEPLOYMENT_FAILED", application, build_name, batches)
                return False

            #run batch done hook
            self.run_hook("AUTO_DEPLOYMENT_BATCH_DONE", application, build_name, batches, batch_number=i)

            deploy_doc = self.datasvc.deploysvc.GetDeployment(application, self.deployment_id)
            assert deploy_doc
            if deploy_doc['status'] == 'error':
                self.datasvc.jobsvc.NewJobData({"message": "detected failed deployment so aborting further batches"})
                self.datasvc.jobsvc.NewJobData({"RollingDeployment": "error"})
                self.run_hook("AUTO_DEPLOYMENT_FAILED", application, build_name, batches)
                return False

            if i != (len(batches)-1):
                pause = ordered_pause if b['ordered_gitdeploy'] else rolling_pause
                msg = "pausing for {} seconds between batches ({})".format(pause,
                                                                           "ordered" if b['ordered_gitdeploy']
                                                                           else "batch complete")
                self.datasvc.jobsvc.NewJobData({"RollingDeployment": msg})
                logging.debug("RollingDeployController: {}".format(msg))
                time.sleep(pause)

        #run post hook
        self.run_hook("AUTO_DEPLOYMENT_COMPLETE", application, build_name, batches, target=target)
        return True

def determine_deployabe_servers(all_gd_servers, specified_servers):
    return list(set(all_gd_servers).intersection(set(specified_servers)))

def _threadsafe_process_gitdeploy(gddoc, build_doc, settings, job_id, deployment_id):
    '''
    Threadsafe function for processing a single gitdeploy during a deployment.
    Creates own instance of datasvc, etc.
    '''

    package = gddoc['package']
    package_doc = build_doc['packages'][package]

    client, datasvc = regen_datasvc(settings, job_id)
    gdm = gitservice.GitDeployManager(gddoc, datasvc)
    gitrepo_name = gddoc['location']['gitrepo']['name']

    datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                              progress=10,
                                              step='Checking out default branch')

    try:
        res = gdm.checkout_default_branch()
    except:
        exc_msg = str(sys.exc_info()[1]).split('\n')
        exc_msg.insert(0, "ERROR: checkout_default_branch")
        datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                                  step=exc_msg)
        return

    logging.debug("_threadsafe_process_gitdeploy: git checkout output: {}".format(str(res)))

    if gdm.last_build == build_doc['build_name']:
        datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gitrepo_name: "already processed"}})
        datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                              progress=100,
                                              step='Complete (already processed)')
    else:
        datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                              progress=25,
                                              step='Decompressing package to repository')

        datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "processing"}})

        try:
            gdm.decompress_to_repo(package_doc)
        except:
            exc_msg = str(sys.exc_info()[1]).split('\n')
            exc_msg.insert(0, "ERROR: decompress_to_repo")
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                                      step=exc_msg)
            return

        datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                              progress=50,
                                              step='Checking for changes')

        logging.debug("_threadsafe_process_gitdeploy: Checking for changes")
        try:
            res = gdm.check_repo_status()
        except:
            exc_msg = str(sys.exc_info()[1]).split('\n')
            exc_msg.insert(0, "ERROR: check_repo_status")
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                                      step=exc_msg)
            return
        logging.debug("_threadsafe_process_gitdeploy: git status results: {}".format(str(res)))

        if "nothing to commit" in res:
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                              progress=100,
                                              step='Complete (no changes found)')
            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "no changes"}})
        else:
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                              progress=60,
                                              step='Adding changes to repository')
            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "adding to repository"}})
            try:
                res = gdm.add_files_to_repo()
            except:
                exc_msg = str(sys.exc_info()[1]).split('\n')
                exc_msg.insert(0, "ERROR: add_files_to_repo")
                datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                                          step=exc_msg)
                return
            logging.debug("_threadsafe_process_gitdeploy: git add result: {}".format(str(res)))

            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                              progress=70,
                                              step='Committing changes to repository')
            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "committing"}})
            try:
                res = gdm.commit_to_repo(build_doc['build_name'])
            except:
                exc_msg = str(sys.exc_info()[1]).split('\n')
                exc_msg.insert(0, "ERROR: commit_to_repo")
                datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                                          step=exc_msg)
                return
            logging.debug("_threadsafe_process_gitdeploy: git commit result: {}".format(str(res)))

            try:
                commit_hash = gdm.get_latest_commit_hash()
                datasvc.deploysvc.UpdateDeployment(gddoc['application'], deployment_id,
                                                   {'commits': {gitrepo_name: str(commit_hash)}})
                logging.debug("_threadsafe_process_gitdeploy: git commit hash: {}".format(str(commit_hash)))
            except:
                exc_msg = str(sys.exc_info()[1]).split('\n')
                exc_msg.insert(0, "ERROR: get_commit_hash")
                datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                                          step=exc_msg)

            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "checking diff"}})
            try:
                res = gdm.inspect_latest_diff()
            except:
                exc_msg = str(sys.exc_info()[1]).split('\n')
                exc_msg.insert(0, "ERROR: inspect_latest_diff")
                datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
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

            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                              changed_files=changed_files)

            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                              progress=90,
                                              step='Pushing changes to gitprovider')
            datasvc.jobsvc.NewJobData({"ProcessGitdeploys": {gddoc['name']: "pushing"}})
            try:
                res = gdm.push_repo()
            except:
                exc_msg = str(sys.exc_info()[1]).split('\n')
                exc_msg.insert(0, "ERROR: push_repo")
                datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                                          step=exc_msg)
                return
            logging.debug("_threadsafe_process_gitdeploy: git push result: {}".format(str(res)))
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                              progress=100,
                                              step='Complete')
        try:
            gdm.update_repo_last_build(build_doc['build_name'])
        except:
            exc_msg = str(sys.exc_info()[1]).split('\n')
            exc_msg.insert(0, "ERROR: update_repo_last_build")
            datasvc.deploysvc.UpdateDeployment_Phase1(gddoc['application'], deployment_id, gitrepo_name,
                                                      step=exc_msg)
            return

def _threadsafe_pull_callback(results, tag, **kwargs):
    '''
    Passed to run_slses_async and is used to provide realtime updates to users polling the deploy job object
    '''
    try:
        assert all([arg in kwargs for arg in ('datasvc', 'application', 'deployment_id', 'batch_number', 'gitdeploy')])
    except AssertionError:
        #can't log anything to the job object because we may not have a valid DataService instance
        logging.error("***************** _threadsafe_pull_callback: AssertionError: incorrect kwargs ****************")
        return

    datasvc = kwargs['datasvc']
    app = kwargs['application']
    deployment_id = kwargs['deployment_id']
    batch_number = kwargs['batch_number']
    gitdeploy = kwargs['gitdeploy']
    try:
        datasvc.jobsvc.NewJobData({"DeployServers": {"results": results, "tag": tag}})
        for r in results:
            #callback results always have a 'ret' key but underneath it may be a simple string or a big complex object
            #for state call results. We have to unpack the state results if necessary
            this_result = results[r]['ret']
            datasvc.jobsvc.NewJobData(this_result)
            if elita.util.type_check.is_dictlike(this_result):  # state result
                for state_res in this_result:
                    if "result" in this_result[state_res]:
                        state_comment = this_result[state_res]['comment'] if 'comment' in this_result[state_res] else state_res
                        stdout = this_result[state_res]["changes"]["stdout"] if 'changes' in this_result[state_res] and 'stdout' in this_result[state_res]['changes'] else "(none)"
                        stderr = this_result[state_res]["changes"]["stderr"] if 'changes' in this_result[state_res] and 'stderr' in this_result[state_res]['changes'] else "(none)"
                        if not this_result[state_res]["result"]:    #error
                            logging.debug("_threadsafe_pull_callback: got error result ({}; {})".format(gitdeploy, r))
                            datasvc.jobsvc.NewJobData({'status': 'error', 'message': 'failing deployment due to detected error'})
                            datasvc.deploysvc.UpdateDeployment_Phase2(app, deployment_id, gitdeploy, [r], batch_number,
                                                                      state="FAILURE: {}; stderr: {}; stdout: {}".format(state_comment, stderr, stdout))
                            datasvc.deploysvc.FailDeployment(app, deployment_id)
                        else:
                            logging.debug("_threadsafe_pull_callback: got successful result ({}; {}): {}".format(gitdeploy, r, state_comment))
                            datasvc.deploysvc.UpdateDeployment_Phase2(app, deployment_id, gitdeploy, [r], batch_number,
                                                          state=state_comment,
                                                          progress=66)
            else:   # simple result
                logging.debug("_threadsafe_pull_callback: got simple return instead of results ({}; {})".format(gitdeploy, r))
                datasvc.deploysvc.UpdateDeployment_Phase2(app, deployment_id, gitdeploy, [r], batch_number,
                                                          state="simple return: {}".format(results[r]['ret']))
    except:
        exc_type, exc_obj, tb = sys.exc_info()
        datasvc.jobsvc.NewJobData({"_threadsafe_pull_callback EXCEPTION": traceback.format_exception(exc_type, exc_obj, tb)})
        datasvc.deploysvc.FailDeployment(app, deployment_id)

def _threadsafe_pull_gitdeploy(application, gitdeploy_struct, queue, settings, job_id, deployment_id, batch_number):
    '''
    Thread-safe way of performing a deployment SLS call for one specific gitdeploy on a group of servers
    gitdeploy_struct: { "gitdeploy_name": [ list_of_servers_to_deploy_to ] }
    '''
    # Wrap in a big try/except so we can log any failures in phase2 progress and fail the deployment
    try:
        assert settings
        assert job_id
        assert gitdeploy_struct
        client, datasvc = regen_datasvc(settings, job_id)
        gd_name = gitdeploy_struct.keys()[0]
        servers = gitdeploy_struct[gd_name]
    except:
        exc_msg = str(sys.exc_info()[1]).split('\n')
        logging.error("************* _threadsafe_pull_gitdeploy: preamble: {} *********************".format(exc_msg))
        return
    try:
        assert application
        assert queue
        assert deployment_id
        assert all([elita.util.type_check.is_string(gd) for gd in gitdeploy_struct])
        assert all([elita.util.type_check.is_seq(gitdeploy_struct[gd]) for gd in gitdeploy_struct])
        assert isinstance(batch_number, int) and batch_number >= 0
        sc = salt_control.SaltController(datasvc)
        rc = salt_control.RemoteCommands(sc)
        assert len(gitdeploy_struct) == 1

        datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, servers, batch_number,
                                                  progress=10,
                                                  state="Beginning deployment")

        #until salt Helium is released, we can only execute an SLS *file* as opposed to a single module call
        sls_map = {sc.get_gitdeploy_entry_name(application, gd_name): servers}
        if len(servers) == 0:
            datasvc.jobsvc.NewJobData({"DeployServers": {gd_name: "no servers"}})
            return True

        gd_doc = datasvc.gitsvc.GetGitDeploy(application, gd_name)
        branch = gd_doc['location']['default_branch']
        path = gd_doc['location']['path']

        #verify that we have salt connectivity to the target. Do three consecutive test.pings with 10 second timeouts
        #if all target servers don't respond by the last attempt, fail deployment
        i = 1
        while True:
            datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, servers, batch_number,
                                                      progress=15,
                                                      state="Verifying salt connectivity (try: {})".format(i))
            res = rc.ping(servers)
            if all([s in res for s in servers]):
                logging.debug("_threadsafe_process_gitdeploy: verify salt: all servers returned (try: {})".format(i))
                break
            else:
                missing_servers = list(set(servers) - set(res.keys()))
                logging.debug("_threadsafe_process_gitdeploy: verify salt: error: servers missing: {} (try {})".format(missing_servers, i))
            if i >= 3:
                datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, missing_servers, batch_number,
                                                      progress=15,
                                                      state="ERROR: no salt connectivity!".format(i))
                datasvc.deploysvc.FailDeployment(application, deployment_id)
                logging.error("No salt connectivity to servers: {} (after {} tries)".format(missing_servers, i))
                return False
            i += 1

        #delete stale git index lock if it exists
        datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, servers, batch_number,
                                                  progress=25,
                                                  state="Removing git index lock if it exists")
        res = rc.rm_file_if_exists(servers, "{}/.git/index.lock".format(path))
        logging.debug("_threadsafe_process_gitdeploy: delete git index lock results: {}".format(str(res)))

        #clear uncommitted changes on targets
        datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, servers, batch_number,
                                                  progress=33,
                                                  state="Clearing uncommitted changes")

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
                                                  state="ERROR: {}".format(errors[e]))
            logging.debug("_threadsafe_pull_gitdeploy: SLS error servers: {}".format(errors.keys()))
            logging.debug("_threadsafe_pull_gitdeploy: SLS error responses: {}".format(errors))

        if len(successes) > 0:
            datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, successes.keys(), batch_number,
                                                      progress=100, state="Complete")

        missing = list(set([host for r in res for host in r]).difference(set(servers)))
        if missing:
            datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, missing, batch_number,
                                                      state="ERROR: no results (timed out waiting for salt?)")
            logging.debug("_threadsafe_pull_gitdeploy: error: empty results for: {}; possible salt timeout".format(missing))
            datasvc.jobsvc.NewJobData({"_threadsafe_pull_gitdeploy": "empty results for {}".format(missing)})
            datasvc.deploysvc.FailDeployment(application, deployment_id)

        deploy_results = {
            gd_name: {
                "raw_results": res,
                "errors": len(errors) > 0,
                "error_results": errors,
                "successes": len(successes) > 0,
                "success_results": successes
            }
        }

        queue.put_nowait(deploy_results)

        datasvc.jobsvc.NewJobData({
            "DeployServers": deploy_results
        })

        logging.debug("_threadsafe_pull_gitdeploy: finished ({})".format(gitdeploy_struct))

    except:
        exc_type, exc_obj, tb = sys.exc_info()
        exc_msg = "ERROR: Exception in _threadsafe_pull_gitdeploy: {}".format(traceback.format_exception(exc_type, exc_obj, tb))
        datasvc.deploysvc.UpdateDeployment_Phase2(application, deployment_id, gd_name, servers, batch_number,
                                                  state=exc_msg)
        datasvc.deploysvc.FailDeployment(application, deployment_id)


class DeployController:
    '''
    Class that runs deploys. Only knows about server/gitdeploy pairs, so is used for both manual-style deployments
    and group/environment deployments.
    '''

    __metaclass__ = elita.util.LoggingMetaClass

    def __init__(self, datasvc, deployment_id):
        self.deployment_id = deployment_id
        self.datasvc = datasvc

    def run(self, app_name, build_name, servers, gitdeploys, parallel=True, batch_number=0):
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

        build_doc = self.datasvc.buildsvc.GetBuild(app_name, build_name)
        gitdeploy_docs = {gd: self.datasvc.gitsvc.GetGitDeploy(app_name, gd) for gd in gitdeploys}

        queue = billiard.Queue()
        procs = list()

        #we need to get a list of gitdeploys with unique gitrepos, so build a reverse mapping
        gitrepo_gitdeploy_mapping = {gitdeploy_docs[gd]['location']['gitrepo']['name']: gd for gd in gitdeploys}

        self.datasvc.deploysvc.StartDeployment_Phase(app_name, self.deployment_id, 1)
        for gr in gitrepo_gitdeploy_mapping:
            gd = gitrepo_gitdeploy_mapping[gr]
            gddoc = gitdeploy_docs[gd]
            if parallel:
                p = billiard.Process(target=_threadsafe_process_gitdeploy, name=gd,
                                     args=(gddoc, build_doc, self.datasvc.settings,
                                     self.datasvc.job_id, self.deployment_id))
                p.start()
                procs.append(p)

            else:
                _threadsafe_process_gitdeploy(gddoc, build_doc, self.datasvc.settings,
                                              self.datasvc.job_id, self.deployment_id)

        if parallel:
            error = False
            for p in procs:
                p.join(150)
                if p.is_alive():
                    p.terminate()
                    logging.error("ERROR: _threadsafe_process_gitdeploy: timeout waiting for child process ({})!".
                                  format(p.name))
                    self.datasvc.jobsvc.NewJobData({'status': 'error',
                                                    'message': 'timeout waiting for child process (process_gitdeploy: {}'.format(p.name)})
                    self.datasvc.deploysvc.UpdateDeployment_Phase1(app_name, self.deployment_id, p.name,
                                                          step="ERROR: timed out waiting for child process")
                    error = True
                if p.exitcode < 0 or p.exitcode > 0:
                    msg = "process killed by signal {}!".format(abs(p.exitcode)) if p.exitcode < 0 \
                        else "process died with exit code {}".format(p.exitcode)
                    logging.error("_threadsafe_process_gitdeploy: {}".format(msg))
                    self.datasvc.jobsvc.NewJobData({'status': 'error',
                                                    'message': '{} (process_gitdeploy: {}'.format(msg, p.name)})
                    self.datasvc.deploysvc.UpdateDeployment_Phase1(app_name, self.deployment_id, p.name,
                                                                   step="ERROR: {}".format(msg))
                    error = True
            if error:
                self.datasvc.deploysvc.FailDeployment(app_name, self.deployment_id)
                return False, None

        servers_by_gitdeploy = {gd: determine_deployabe_servers(gitdeploy_docs[gd]['servers'], servers) for gd in gitdeploy_docs}

        queue = billiard.Queue()
        procs = list()
        self.datasvc.deploysvc.StartDeployment_Phase(app_name, self.deployment_id, 2)
        for gd in servers_by_gitdeploy:
            if parallel:
                p = billiard.Process(target=_threadsafe_pull_gitdeploy, name=gd,
                                            args=(app_name, {gd: servers_by_gitdeploy[gd]}, queue, self.datasvc.settings,
                                                  self.datasvc.job_id, self.deployment_id, batch_number))
                p.start()
                procs.append(p)
            else:
                _threadsafe_pull_gitdeploy(app_name, {gd: servers_by_gitdeploy[gd]}, queue, self.datasvc.settings,
                                           self.datasvc.job_id, self.deployment_id, batch_number)

        # pull from queue prior to joining to avoid deadlock
        results = list()
        i = 0
        while i < len(procs):
            results.append(queue.get(150))
            i += 1

        if parallel:
            error = False
            for p in procs:
                p.join(150)
                if p.is_alive():
                    p.terminate()
                    logging.error("_threadsafe_pull_gitdeploy: timeout waiting for child process ({})!".
                                  format(p.name))
                    self.datasvc.jobsvc.NewJobData({'status': 'error',
                                                    'message': 'timeout waiting for child process (pull_gitdeploy: {}'.format(p.name)})
                    self.datasvc.deploysvc.UpdateDeployment_Phase2(app_name, self.deployment_id, p.name,
                                                                   servers_by_gitdeploy[p.name], batch_number,
                                                                   state="ERROR: timeout waiting for child process")
                    error = True
                if p.exitcode < 0 or p.exitcode > 0:
                    msg = "process killed by signal {}!".format(abs(p.exitcode)) if p.exitcode < 0 \
                        else "process died with exit code {}".format(p.exitcode)
                    logging.error("_threadsafe_pull_gitdeploy: {}".format(msg))
                    self.datasvc.jobsvc.NewJobData({'status': 'error',
                                                    'message': '{} (pull_gitdeploy: {}'.format(msg, p.name)})
                    self.datasvc.deploysvc.UpdateDeployment_Phase2(app_name, self.deployment_id, p.name,
                                                                   servers_by_gitdeploy[p.name], batch_number,
                                                                   state="ERROR: {}".format(msg))
                    error = True
            if error:
                self.datasvc.deploysvc.FailDeployment(app_name, self.deployment_id)
                return False, None

        if not results:
            return False, results

        for r in results:
            for gd in r:
                if r[gd]['errors']:
                    return False, results

        #update deployed_build
        for gd in gitdeploys:
            gdm = gitservice.GitDeployManager(gitdeploy_docs[gd], self.datasvc)
            gdm.update_last_deployed(build_name)

        return True, results

