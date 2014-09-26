================
Plugin Reference
================

Elita plugins are constructed by creating a Python setuptools-compliant module which declares entry points with the
group ``elita_modules``.

setup.py:

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


Note that the two entry points refer to functions within the top-level ``__init__.py`` for this module. ``register_actions``
and ``register_hooks`` are both required (but can be named anything in your module, as long as the ``entry_points``
mapping is correct). Both functions must return a dictionary with keys corresponding to application
names (more details below).

.. ATTENTION::
   Note that register_hooks and register_actions are executed at the beginning of every Elita request globally (required
   for dynamic request routing), therefore do not perform any complex calculations or I/O within this function. In nearly
   every case you should just declare and return a static dictionary consisting of action/hook definitions.


register_actions
----------------

This function declares custom HTTP endpoints. It should return a dictionary mapping application names to a list of
action definitions. An action definition is a dictionary with the following keys:

* *params* - a dictionary of URL parameters the action supports. It must map to a dictionary containing the following
  keys:

  - *type* - a string describing the type of value the parameter expects
  - *description* - a description of the parameter's purpose

* *callable* - the function object to execute when the endpoint is triggered via POST

The name of the action (and therefore the URL endpoint) will be the name of the callable (ie, ``callable.__name__``)

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
                                "testing": {
                                    "type": "boolean (string)",
                                    "description": "do not delete widgets for real (true or false)"
                                },
                                "count": {
                                    "type": "integer",
                                    "description": "number of widgets to delete"
                                }
                            },
                            "callable": DeleteWidgets
                        }
                    ]
       }

The above example will create the following action endpoint:

https://elita:2719/app/my_application/actions/DeleteWidgets

...which could be triggered as:

.. sourcecode:: bash

   $ http POST 'https://elita:2719/app/my_application/actions/DeleteWidgets?testing=true&count=10'

All actions are triggered by POST request (which executes the function pointed to by ``callable``). All declared
parameters must be present or a 400 Bad Request response is returned and the action is not executed. For optional
parameters, do not specify anything in the declaration and then check for them in the executed function.

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

The above registers hooks that will execute whenever a build is uploaded, a gitdeploy is initialized and deinitialized
from a server and whenever a deployment commit is performed (reading from top to bottom).


Actions
-------

Action functions are passed the following parameters:

* *datasvc* - This is a black box object that contains all API functionality required to interact with Elita (see below).
* *params* - A dictionary of URL parameters passed in the request. It is guaranteed to have at least all parameters
  declared as part of the action definition (and may have additional parameters).

Actions are always executed in an asynchronous context. When a user issues a POST request to the endpoint, the action
is asynchronously triggered and a job ID is returned in the HTTP response, referring to a job object that can be polled
to view action status/information.


Hooks
-----

Hook functions are passed the following parameters:

* datasvc - (see below)
* hook_parameters - A dictionary of hook-specific items.

Hooks are always executed within an existing asynchronous context. The exact context is hook-specific.

Supported hooks:

BUILD_UPLOAD_SUCCESS
  Triggered after a build is successfully stored and packaging (if any) is complete.

  Parameters:

  * *storage_dir* - path in filesystem where master package is located
  * *filename* - filename of master package
  * *file_type* - type of file (zip, etc.) See SupportedFileType in builds.py

GITDEPLOY_INIT_PRE
  Triggered immediately before a gitdeploy is initialized on a server.

  Parameters:

  * *server_list* - list of server names the gitdeploy will be initialized on
  * *gitdeploy* - the gitdeploy document for the gitdeploy that will be initialized

GITDEPLOY_INIT_POST
  Triggered immediately after a gitdeploy is successfully initialized on a server.

  Parameters:

  * *server_list* - list of server names the gitdeploy was initialized on
  * *gitdeploy* - the gitdeploy document for the gitdeploy that was initialized

GITDEPLOY_DEINIT_PRE
  Triggered immediately before a gitdeploy is deinitialized (removed) from a server.

  Parameters:

  * *server_list* - list of server names the gitdeploy will be deinitialized from
  * *gitdeploy* - the gitdeploy document for the gitdeploy that will be deinitialized

GITDEPLOY_DEINIT_POST
  Triggered immediately after a gitdeploy is successfully deinitialized (removed) from a server.

  Parameters:

  * *server_list* - list of server names the gitdeploy was deinitialized on
  * *gitdeploy* - the gitdeploy document for the gitdeploy that was deinitialized

GITDEPLOY_COMMIT_DIFF
  Triggered immediately after a package is committed to a gitdeploy during a deployment. Intended so plugins can take
  some action with the commit diff output.

  Parameters:

  * *files* - a list of changed filenames (relative to the root of the package/gitrepo)
  * *gitdeploy* - the gitdeploy document for the gitdeploy that was initialized

AUTO_DEPLOYMENT_START
  Triggered at the beginning of a groups/environments automatic deployment (not a deployment to individual servers/gitdeploys).

  Parameters:

  * *build* - build name to be deployed
  * *target* - target to be deployed to (dictionary with the following keys: "groups", "environments")
  * *batches* - a list of dictionaries (each with keys: "gitdeploys", "servers") representing deployment batches

AUTO_DEPLOYMENT_BATCH_BEGIN
  Triggered at the beginning of each deployment batch.

  * *build* - build name being deployed
  * *batch_number* - batch number (starting at 0)
  * *batches* - same as batches above

AUTO_DEPLOYMENT_BATCH_DONE
  Triggered at the end of each deployment batch.

  * *build* - build name being deployed
  * *batch_number* - batch number (starting at 0)
  * *batches* - same as batches above

AUTO_DEPLOYMENT_COMPLETE
  Triggered at the end of a groups/environments automatic deployment (not a deployment to individual servers/gitdeploys).

  Parameters:

  * *build* - build name deployed
  * *target* - target that was deployed to (dictionary with the following keys: "groups", "environments")
  * *batches* - a list of dictionaries (each with keys: "gitdeploys", "servers") representing deployment batches

Datasvc
-------

The ``datasvc`` ("DataService") object passed to actions and hooks is a black box object that contains all API functionality
required to interact with Elita. There is no separate plugin API (yet), so datasvc consists of the internal data layer
as used by the Elita codebase itself.

For a comprehensive list of classes/methods available, see the generated apidocs (elita/doc/apidocs/ in the source)
or the DataService family of classes in models.py. Note that all classes are already instantiated within the ``datasvc``
object.

Example data layer objects (may be incomplete):

* ``datasvc.appsvc``    -   Application data methods
* ``datasvc.buildsvc``  -   Build data methods
* ``datasvc.gitsvc``    -   Gitprovider/gitrepo/gitdeploy data methods
* ``datasvc.groupsvc``  -   Group data methods
* ``datasvc.serversvc`` -   Server data methods

The data layer primarily works with "documents" as represented by MongoDB. These are dictionary objects containing keys
representing the fields of the corresponding Mongo document.

Some examples:

.. sourcecode:: python

   build_doc = datasvc.buildsvc.GetBuild('my_application', '123-master')   #application name and build name
   # build_doc is a dictionary like: { "app_name": "my_application", "build_name": "123-master" }

   builds = datasvc.buildsvc.GetBuilds('my_application')
   # builds is a list of build names associated with my_application

   datasvc.buildsvc.DeleteBuild('my_application', '123-master')
   datasvc.buildsvc.NewBuild('my_application', '124-master', {})    # empty attributes field
   datasvc.buildsvc.UpdateBuild('my_application', '124-master', {'attributes': { 'foo': 'bar'}})  #change attributes field

All data layer objects share a naming convention for methods. "Get{Object}" gets one specific instance (document) of the object,
"Get{Object}s" gets a list of all object names of that type, "New{Object}" creates a new object, "Delete{Object}" deletes
an object and "Update{Object}" will modify an existing object.

``datasvc`` also contains objects for interacting with salt and doing remote commands on servers.

``remote_controller`` (instance of ``RemoteCommands``) is an abstracted interface for higher-level operations, while
``salt_controller`` (instance of ``SaltController``) is for lower-level direct salt commands (and is not portable in
the event of Elita switching away from salt for remote execution).

.. sourcecode:: python

   # delete a directory
   # note that server OS (win/unix) will be automatically detected and the appropriate commands sent to each subgroup
   results = datasvc.remote_controller.delete_directory(['server01'], '/opt/foobar')

.. sourcecode:: python

   # execute an arbitrary salt command on some server
   # blocks waiting on results
   results = datasvc.salt_controller.salt_command(['server01'], 'test.ping', [])


Action/Hook Progress
--------------------

Actions and hooks are always executed in an asynchronous context and are therefore associated with a job ID. A job ID is
a UUID that refers to a Job object.

Job objects can be polled by the end user in the following way (see also: :ref:`Job Endpoints <job-endpoints>`):

.. sourcecode:: bash

   # if the job ID is: f434540d-5bfd-46b5-9045-12e8cecf47b3
   $ http GET 'http://elita:2719/job/f434540d-5bfd-46b5-9045-12e8cecf47b3?results=true

(``results=true`` will return all job data associated with the job, while ``results=false`` will return only a summary
of the job)

Jobs objects are intended to be running logs (in JSON) of what occurred during job execution. Every significant step
should add a new job data entry:

.. sourcecode:: python

   datasvc.jobsvc.NewJobData({'status': 'starting', 'progress': 0})

   # ... do something ...

   datasvc.jobsvc.NewJobData({'status': 'frobnicating the foobar', 'progress': 45})

   # ... more work ...

   datasvc.jobsvc.NewJobData({'status': 'finished', 'progress': 100})

``NewJobData()`` automatically knows the correct job id. The format of the job data message can be any freeform
dictionary object (and can contain lists, numbers, etc) but must be serializable to JSON.

Feel free to also use the logging module, just be aware that it will output to the local Elita log only and will not be
visible to end users.
