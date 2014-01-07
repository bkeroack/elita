import requests
from slugify import slugify

import util

__author__ = 'bkeroack'

class BitBucketData:
    base_url = 'https://api.bitbucket.org/2.0'

#callables for async execution
def create_bitbucket_repo(datasvc, gitprovider, name):
    bbsvc = BitBucketRepoService(gitprovider)
    return bbsvc.create_repo(name)

def create_github_repo(datasvc, gitprovider, name):
    return {'error': 'not implemented'}


class GitRepoService:
    def __init__(self, gitprovider):
        self.gp_type = gitprovider['type']
        self.auth = gitprovider['auth']
        self.base_url = gitprovider['base_url']

    def create_repo(self, name):
        util.debugLog(self, "create_repo not implemented")

class GitHubRepoService(GitRepoService):
    pass

class BitBucketRepoService(GitRepoService):
    def create_repo(self, name):
        util.debugLog(self, "Creating repo: {}".format(name))
        slug = slugify(name)
        username = self.auth['username']
        password = self.auth['password']
        json_body = {
            'scm': 'git',
            'name': name,
            'is_private': 'true',
            'description': "Created by daft",
            'forking_policy': 'no_forks'
        }
        r = requests.post("{}/repositories/{}/{}".format(BitBucketData.base_url, username, slug), data=json_body,
                          auth=(username, password))
        return r.text
