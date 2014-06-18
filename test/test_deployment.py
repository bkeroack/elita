import mock
from elita.deployment import deploy
from elita.models import DataService, BuildDataService, GitDataService, JobDataService
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

@mock.patch('elita.deployment.salt_control.SaltController')
@mock.patch('elita.deployment.salt_control.RemoteCommands')
@mock.patch('elita.deployment.gitservice.GitDeployManager')
@mock.patch('pymongo.MongoClient')
@mock.patch('elita.actions.action.regen_datasvc')
def test_simple_deployment(mockSaltController, mockRemoteCommands, mockGitDeployManager, mockMongoClient, mockRegenDatasvc):
    '''
    Test simple deployment to gitdeploys: gd0, gd1; servers: server0, server1
    '''

    servers = ["server0", "server1"]
    gitdeploys = ["gd0", "gd1"]

    mock_datasvc = mock.Mock(spec=DataService)
    mock_datasvc.attach_mock(mock.Mock(spec=BuildDataService), "buildsvc")
    mock_datasvc.attach_mock(mock.Mock(spec=GitDataService), "gitsvc")
    mockGitDeployManager.last_build = "old_build"
    mockRegenDatasvc.return_value = None, mock.Mock(spec=DataService)
    mock_datasvc.settings = {
        'elita.mongo.host': 'localhost',
        'elita.mongo.port': 0,
        'elita.mongo.db': 'none'
    }
    mock_datasvc.job_id = ""
    mock_datasvc.gitsvc.GetGitDeploy = return_gitdeploy
    mock_datasvc.buildsvc.GetBuildDoc = return_build

    dc = deploy.DeployController(mock_datasvc)

    dc.run("example_app", "example_build", servers, gitdeploys)

    for o in mockSaltController, mockRemoteCommands, mockGitDeployManager, mockMongoClient, mockRegenDatasvc, mock_datasvc, mock_datasvc.buildsvc, mock_datasvc.gitsvc:
        print("{}: {}".format(o, o.mock_calls))

    #assert False
