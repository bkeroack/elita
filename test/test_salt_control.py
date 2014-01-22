__author__ = 'bkeroack'

import unittest2
import tempfile
import yaml
import daft.salt_control
import shutil
import pprint

class SaltControllerTests(unittest2.TestCase):
    def setUp(self):
        self.dtemp = tempfile.mkdtemp()
        self.tempfile = '{}/testgitdeploy.sls'.format(self.dtemp)
        self.tempfile_config = "{}/master".format(self.dtemp)
        self.saltsettings = {
            'file_roots': {
                'base': ['/']
            }
        }
        self.testsls = {
            'existing_prepull': {
                'cmd.run': [
                    {
                        'name': 'echo foo'
                    },
                    {
                        'order': 0
                    }
                ]
            },
            'unrelated_state': {
                'cmd.run': [
                    {
                        'name': 'echo bar'
                    }
                ]
            },
            'gitdeploy_existing': {
                'cmd.run': [
                    {
                        'name': 'echo existing gitdeploy'
                    },
                    {
                        'cwd': '/another/fake/path'
                    },
                    {
                        'failhard': 'true'
                    },
                    {
                        'order': 1
                    }
                ]
            },
            'existing_postpull': {
                'cmd.run': [
                    {
                        'name': 'echo existing postpull'
                    },
                    {
                        'order': 'last'
                    }
                ]
            }
        }
        with open(self.tempfile, 'w+') as f:
            f.write(yaml.dump(self.testsls))
        with open(self.tempfile_config, 'w+') as f:
            f.write(yaml.dump(self.saltsettings))
        self.settings = {
            'daft.salt.config': "{}/master".format(self.dtemp),
            'daft.salt.dir': self.dtemp
        }

    def tearDown(self):
        shutil.rmtree(self.dtemp)

    def test_add_gitdeploy_to_yaml(self):
        gitdeploy = {
            'name': 'testgitdeploy',
            'options': {
                'favor': "ours",
                'ignore-whitespace': 'true'
            },
            'actions': {
                'prepull': {
                    'newprepull': {
                        'cmd.run': [
                            {
                                'name': 'echo new prepull'
                            }
                        ]
                    }
                },
                'postpull': {
                    'newpostpull': {
                        'cmd.run': [
                            {
                                'name': 'echo new postpull'
                            }
                        ]
                    }
                }
            },
            'location': {
                'path': '/my/fake/path',
                'default_branch': 'mydefaultbranch'
            }
        }
        sc = daft.salt_control.SaltController(self.settings)
        sc.add_gitdeploy_to_yaml(gitdeploy)
        with open(self.tempfile, 'r') as f:
            content = yaml.load(f)
            pp = pprint.PrettyPrinter(indent=4)
            print("content object:")
            print(pp.pformat(content))
            self.assertIn('newprepull', content)
            self.assertIn('newpostpull', content)
            self.assertIn('gitdeploy_testgitdeploy', content)
            self.assertIn('existing_prepull', content)
            self.assertIn('existing_postpull', content)
            self.assertIn('gitdeploy_existing', content)
            self.assertIn('order', content['newprepull']['cmd.run'][1])
            self.assertIn('order', content['newpostpull']['cmd.run'][1])
            self.assertIn('order', content['gitdeploy_testgitdeploy']['cmd.run'][3])
            self.assertIn('order', content['gitdeploy_existing']['cmd.run'][3])
            self.assertIn('order', content['existing_prepull']['cmd.run'][1])
            self.assertIn('order', content['existing_postpull']['cmd.run'][1])
        print("resulting yaml file:")
        with open(self.tempfile, 'r') as f:
            for l in f:
                print(l)