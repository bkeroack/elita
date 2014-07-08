import mock
#from elita.deployment import deploy, salt_control
import elita.deployment.deploy
import elita.deployment.salt_control
from elita.deployment import gitservice
from elita.models import DataService, BuildDataService, GitDataService, JobDataService, GroupDataService
#import logging


def return_gitdeploy(app, name):
    return {
        "application": app,
        "name": name,
        "package": "master",
        "location": {
            "path": "/foo/bar",
            "default_branch": "master"
        },
        "servers": ["server0", "server1"],
        "gitrepo": {

        }
    }


def return_build(app, name):
    return {
        "app_name": app,
        "build_name": name,
        "packages": {
            "master": {
                "file_type": "zip",
                "filename": "/foo/bar/baz.zip"
            }
        }
    }


def setup_mock_datasvc():
    mock_datasvc = mock.Mock(spec=DataService)
    mock_datasvc.attach_mock(mock.Mock(spec=BuildDataService), "buildsvc")
    mock_datasvc.attach_mock(mock.Mock(spec=GitDataService), "gitsvc")
    mock_datasvc.attach_mock(mock.Mock(spec=JobDataService), "jobsvc")
    mock_datasvc.job_id = ""
    mock_datasvc.gitsvc.GetGitDeploy = return_gitdeploy
    mock_datasvc.buildsvc.GetBuildDoc = return_build
    mock_datasvc.settings = {
        'elita.mongo.host': 'localhost',
        'elita.mongo.port': 0,
        'elita.mongo.db': 'none'
    }
    return mock_datasvc


# @mock.patch('elita.deployment.salt_control.SaltController')
# @mock.patch('elita.deployment.salt_control.RemoteCommands')
# @mock.patch('elita.deployment.gitservice.GitDeployManager')
# @mock.patch('elita.deployment.deploy.regen_datasvc')
# def test_simple_deployment(mockRD, mockGitDeployManager, mockRemoteCommands, mockSaltController):
#     '''
#     Test simple deployment to gitdeploys: gd0, gd1; servers: server0, server1
#     '''
#
#     servers = ["server0", "server1"]
#     gitdeploys = ["gd0", "gd1"]
#
#     mock_datasvc = setup_mock_datasvc()
#     mockRD.return_value = None, mock_datasvc
#     mockGitDeployManager.last_build = "nobuild"
#
#     dc = elita.deployment.deploy.DeployController(mock_datasvc)
#
#     ok, results = dc.run("example_app", "example_build", servers, gitdeploys, parallel=False)
#
#     #assert False


def return_group(app, name):
    return {
        "rolling_deploy": name == 'gp0',
        "gitdeploys": ["gd0", "gd1"] if name == 'gp0' else ["gd2", "gd3"]
    }


def return_group_servers(app, name):
    return ['rolling_server{}'.format(x) for x in range(0, 5)] if name == 'gp0' else ['nonrolling_server{}'.format(x) for x in range(0, 5)]

@mock.patch('elita.deployment.salt_control.SaltController')
@mock.patch('elita.deployment.salt_control.RemoteCommands')
@mock.patch('elita.deployment.gitservice.GitDeployManager')
@mock.patch('elita.deployment.deploy.regen_datasvc')
def test_rolling_deployment(mockRD, mockGitDeployManager, mockRemoteCommands, mockSaltController):
    '''
    Test rolling deployment with one rolling group and one non-rolling
    '''

    groups = ["group0", "group1"]
    environments = ["testing"]

    mock_datasvc = setup_mock_datasvc()
    mock_datasvc.groupsvc = mock.Mock(spec=GroupDataService)
    mock_datasvc.groupsvc.GetGroup = return_group
    mock_datasvc.groupsvc.GetGroupServers = return_group_servers
    mockRD.return_value = None, mock_datasvc

    dc = elita.deployment.deploy.DeployController(mock_datasvc)
    rdc = elita.deployment.deploy.RollingDeployController(mock_datasvc, dc)

    rdc.run("example_app", "example_build", {"groups": ["gp0", "gp1"], "environments": ["testing"]}, 2, 30, parallel=False)

    #assert False