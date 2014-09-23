================
Plugin Reference
================

Elita plugins are constructed by creating a Python setuptools-compliant module which declares entry points with the
group "elita_modules".

For example, in setup.py:

.. sourcecode:: python

   setup(
      name="elita_example",
      version="0.1",
      description="Example plugin for elita",
      author="J. Doe",
      author_email="jdoe@example.com",
      packages=find_packages(),
      include_package_data=True,
      install_requires = requires,
      tests_require = requires,
      entry_points="""
      [elita.modules]
      register_actions=elita_example:register_actions
      register_hooks=elita_example:register_hooks
      """
    )


Note that the two entry points refer to functions within the top-level __init__.py for this module. register_actions
and register_hooks are both required. Both functions must return a dictionary with keys corresponding to application
names (more details below).

.. ATTENTION::
   Note that register_hooks and register_actions are executed at the beginning of every Elita request globally, therefore do not do
   any intensive calculations or I/O within this function. In nearly every case you should just declare a static dictionary
   consisting of action/hook definitions and then return it.


register_actions
----------------

This function declares custom HTTP endpoints. It should return a dictionary mapping application names to a list of
action definitions. An action definition is a dictionary with the following keys:

* params - a dictionary of URL parameters the action supports. It must map to a dictionary containing the following
  keys:

- type - a string describing the type of value the parameter expects
- description - a description of the parameter's purpose

* callable - the function object to execute when the endpoint is triggered via POST

The name of the action (and therefore the URL endpoint) will be the name of the callable (ie, callabe.__name__)

.. NOTE::
   Parameter types as described above are not enforced by Elita. They are meant to be descriptive only.

Example:

.. sourcecode:: python

   def register_actions():
       return {
           'my_application':
                    [
                        {
                            "params": {
                                "delete": {
                                    "type": "boolean (string)",
                                    "description": "delete widgets for real (true or false)"
                                },
                                "count": {
                                    "type": "integer",
                                    "description": "number of widgets"
                                }
                            },
                            "callable": DeleteWidgets
                        }
                    ]
       }

The above example will create the following action endpoint:

https://elita:2719/app/my_application/actions/DeleteWidgets

All actions are triggered by POST request (which executes the function pointed to by 'callable'). All declared
parameters must be present or a 400 Bad Request response is returned (and the action is not executed). For optional
parameters, do not specify them in the declaration and then check for them in the executed function.

GET requests on the action endpoint returns the parameter list. No other verbs are supported.


register_hooks
--------------

This function declares hook definitions. In Elita, hooks are named points that are triggered during the execution of
various operations. This function must return a dictionary mapping application names to another dictionary mapping
hook names to function objects.

Example:

.. sourcecode:: python

   def register_hooks():
    return {
        'my_application': {
            'BUILD_UPLOAD_SUCCESS': DeclareUploadedBuild,
            'GITDEPLOY_INIT_PRE': DeclareGitdeployInit,
            'GITDEPLOY_DEINIT_PRE': DeclareGitdeployDeinit,
            'GITDEPLOY_COMMIT_DIFF': DeclareDeploymentDiff
        }

The above declares hooks that will execute whenever a build is uploaded, a gitdeploy is initialized and deinitialized
from a server and whenever a deployment commit is performed (reading from top to bottom).


Actions
-------

Action functions are passed the following parameters:

* datasvc - This is a black box object that contains all API functionality required to interact with Elita (see below).
* params - A dictionary of URL parameters passed in the request. It is guaranteed to have at least all parameters
  declared as part of the action definition.

Actions are always executed in an asynchronous context. When a user issues a POST request to the endpoint, the action
is asynchronously triggered and a job ID is returned, referring to a job object that can be polled to view action
status/information.


Hooks
-----

Hook functions are passed the following parameters:

* datasvc - (see below)
* hook_parameters - A dictionary of hook-specific items.

Hooks are always executed within an existing asynchronous context. The exact context is hook-specific.

Supported hooks (incomplete):

BUILD_UPLOAD_SUCCESS
  Triggered after a build is successfully stored, but before packaging is complete.
  Parameters:
  * storage_dir - path in filesystem where master package is located
  * filename - filename of master package
  * file_type - type of file (zip, etc.) See SupportedFileType in builds.py

Datasvc
-------

The datasvc ("DataService") object passed to actions and hooks is the only way for plugin code to interact with Elita.
There is no formal plugin API (yet), so datasvc consists of the internal data layer API as used by the Elita code
itself.

For a comprehensive list of classes/methods available, see the autogenerated apidocs (elita/doc/apidocs/ in the source)
or the DataService family of classes in models.py. Note that all classes are already instantiated within the datasvc
object.

The data layer primarily works with "documents" as represented by MongoDB. These are dictionary objects containing keys
representing the fields of the corresponding Mongo document. When you call the following:

.. sourcecode::python

   build_doc = datasvc.buildsvc.GetBuild('my_application', '123-master')   #application name and build name

"build_doc" is a document (dictionary) containing the build information.

datasvc also contains objects for interacting with salt and doing remote commands on servers.

"remote_controller" is an abstracted interface for higher-level operations, while "salt_controller" is for lower-level
direct salt commands (and is not portable, in the event of Elita switching away from salt for remote execution).

.. sourcecode::python

   # delete a directory
   # note that server OS (win/unix) will be automatically detected and the appropriate commands sent to each subgroup
   results = datasvc.remote_controller.delete_directory(['server01'], '/opt/foobar')

.. sourcecode::python

   # execute an arbitrary salt command on some server
   # blocks waiting on results
   results = datasvc.salt_controller.salt_command(['server01'], 'test.ping', [])

