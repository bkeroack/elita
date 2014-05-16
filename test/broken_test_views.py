__author__ = 'bkeroack'
#
# import unittest2
# import json
# from pyramid import testing
#
# from elita import views, models
#
#
# class DataModel:
#     def __init__(self):
#         self.app_name = 'dummyapp'
#         self.build_name = '0001'
#         self.blah = None
#         self.root = models.RootApplication()
#         self.root['app'] = models.ApplicationContainer()
#         self.root['app'][self.app_name] = models.Application(self.app_name)
#         self.root['app'][self.app_name]['builds'] = models.BuildContainer(self.app_name)
#         self.root['app'][self.app_name]['builds'][self.build_name] = models.Build(self.app_name, self.build_name)
#         self.root['app'][self.app_name]['subsys'] = models.SubsystemContainer(self.app_name)
#         self.root['app'][self.app_name]['environments'] = models.EnvironmentContainer(self.app_name)
#         self.root['app'][self.app_name]['action'] = models.ActionContainer(self.app_name)
#
#
# class ApplicationContainerViewTest(unittest2.TestCase):
#     def setUp(self):
#         self.req = testing.DummyRequest()
#         self.dm = DataModel()
#         self.req.context = self.dm.root['app']
#         self.config = testing.setUp(request=self.req)
#         self.view = views.ApplicationContainerView(self.req.context, self.req)
#         self.ret = None
#
#     def tearDown(self):
#         #ensure results are serializable
#         json.dumps(self.ret)
#
#     def test_get(self):
#         self.ret = self.view.GET()
#         self.assertIn('applications', self.ret, "application container not in GET")
#         self.assertIn(self.dm.app_name, self.ret['applications'], "application object not in GET")
#
#     def test_put(self):
#         new_name = self.dm.app_name + "2"
#         self.req.params['app_name'] = new_name
#         self.ret = self.view.PUT()
#         self.assertIn('new_application', self.ret['action'], "new_application object not in PUT results")
#         self.assertIn('name', self.ret['action']['new_application'], "application container not in PUT results")
#         self.assertEqual(new_name, self.ret['action']['new_application']['name'],
#                          "application name does not match in PUT results")
#
#     def test_delete(self):
#         self.req.params['app_name'] = self.dm.app_name
#         self.ret = self.view.DELETE()
#         self.assertIn('delete_application', self.ret['action'], "delete_application object not in DELETE results")
#         self.assertEqual(self.dm.app_name, self.ret['action']['delete_application'], "application name does not match in DELETE results")
#
#
# class ApplicationViewTest(unittest2.TestCase):
#     def setUp(self):
#         self.req = testing.DummyRequest()
#         self.dm = DataModel()
#         self.req.context = self.dm.root['app'][self.dm.app_name]
#         self.config = testing.setUp(request=self.req)
#         self.view = views.ApplicationView(self.req.context, self.req)
#         self.ret = None
#
#     def tearDown(self):
#         #ensure results are serializable
#         json.dumps(self.ret)
#
#     def test_get(self):
#         self.ret = self.view.GET()
#         self.assertIn('application', self.ret, "application object not in GET")
#
# class BuildContainerViewTest(unittest2.TestCase):
#     def setUp(self):
#         self.req = testing.DummyRequest()
#         self.dm = DataModel()
#         self.req.context = self.dm.root['app'][self.dm.app_name]['builds']
#         self.config = testing.setUp(request=self.req)
#         self.view = views.BuildContainerView(self.req.context, self.req)
#         self.ret = None
#
#     def tearDown(self):
#         #ensure results are serializable
#         json.dumps(self.ret)
#
#     def test_get(self):
#         self.ret = self.view.GET()
#         self.assertIn('application', self.ret, "application object not in GET")
#         self.assertIn('builds', self.ret, "builds container not in GET")
#         self.assertIn(self.dm.build_name, self.ret['builds'], "build name not in builds container in GET")
#
#     def test_put(self):
#         new_name = self.dm.build_name + "2"
#         self.req.params['build_name'] = new_name
#         self.ret = self.view.PUT()
#         self.assertIn('new_build', self.ret['action'], "new_build action not found in PUT results")
#         self.assertEqual(self.dm.app_name, self.ret['action']['new_build']['application'],
#                          "application name doesn't match in PUT results")
#         self.assertEqual(new_name, self.ret['action']['new_build']['build_name'],
#                          "build name doesn't match in PUT results")
#
#
