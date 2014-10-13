=====================
Application Endpoints
=====================
(only supported verbs are shown for each endpoint)

.. contents:: Contents

Applications
------------

View Applications
^^^^^^^^^^^^^^^^^

.. http:get::   /app

   Returns terse list of applications


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/app'


View Application
^^^^^^^^^^^^^^^^

.. http:get::   /app/(string: app_name)

   Returns detail about the application including creation datetime, child resources available and a census of
   environments/groups/servers/gitdeploys and the builds deployed to them.

   The format of census is as follows:

   .. sourcecode:: json

      {
        "ENVIRONMENT_NAME": {
            "GROUP_NAME": {
                "SERVER_NAME": {
                    "GITDEPLOY_NAME": {
                        "committed": "BUILD_NAME",
                        "deployed": "BUILD_NAME"
                    }
                }
            }
        }
      }

   The difference between *committed* and *deployed* occurs when different gitdeploys share a common gitrepo. If
   gitdeployA and gitdeployB share a common gitrepoFoo, after FooBuild is deployed to gitdeployA (or any groups that
   contain gitdeployA), FooBuild will be shown as committed and deployed to gitdeployA. However it will be only shown
   as *committed* to gitdeployB (because it shares gitrepoFoo), while not deployed yet (the *deployed* field will still
   show the previous build). This can also happen with failed rolling deployments when only a fraction of the servers
   in a group are successfully deployed to.

   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/app/widgetmaker'


Create Application
^^^^^^^^^^^^^^^^^^

.. http:put::   /app

   :param app_name: application name
   :type app_name: string

   Create a new application.


   **Example request**:

   .. sourcecode:: bash

      $ curl -XPUT '/app?app_name=widgetmaker'


Delete Application
^^^^^^^^^^^^^^^^^^

.. http:delete::   /app/(string: app_name)

   Remove an application.

   .. WARNING::
      This will also delete all data associated with that application. This cannot be undone.

   **Example request**:

   .. sourcecode:: bash

      $ curl -XDELETE '/app/widgetmaker'


Builds
------

View Builds
^^^^^^^^^^^

.. http:get::   /app/(string: app_name)/builds

   Returns list of all application builds.


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/app/widgetmaker/builds'


Create Build
^^^^^^^^^^^^

.. http:put::   /app/(string: app_name)/builds

   :param build_name: build name
   :jsonparam string body: JSON object containing optional attributes
   :type build_name: string

   Create a new build object.

   **Example request**:

   .. sourcecode:: bash

      $ curl -XPUT '/app/widgetmakers/builds?build_name=1-master' -d '{ "attributes": { "branch_name": "master" } }'


Modify Build
^^^^^^^^^^^^

.. http:patch::   /app/(string: app_name)/builds/(string: build_name)

   :jsonparam string body: JSON object containing optional attributes to modify

   Modify the attributes of a build object.

   .. NOTE::
      Attributes is the only valid key to modify. The provided attributes attribute will replace whatever is
      currently on the build object.

   **Example request**:

   .. sourcecode:: bash

      $ curl -XPATCH '/app/widgetmakers/builds/1-master' -d '{ "attributes": { "branch_name": "something-else" } }'


Upload Build
^^^^^^^^^^^^

.. http:post::   /app/(string: app_name)/builds/(string: build_name)

   :param file_type: file type (either "zip", "tar.gz" or "tar.bz2")
   :type file_type: string
   :param indirect_url: URL-encoded location to download the build from (optional, only for indirect uploads)
   :type indirect_url: string
   :param verify: (optional) If doing indirect upload, verify SSL certificate on indirect_url if present (defaults to True)
   :type verify: string (boolean)
   :param package_map: (optional) name of package map to apply to the build (if not specified, only the master package will be created)
   :type package_map: string
   :formparameter build: File data (optional, only if indirect_url isn't specified)

   Upload a build. This can be done either directly by including file data in a form post,
   or indirectly by providing a URL-encoded location that elita can download the build from.

   Optionally, the name of a package map can be supplied in the package_map parameter. After upload is successful, the
   package map will be applied to the build, creating all packages specified in the map.

   .. ATTENTION::
      The build object must created first (via PUT; see above) before data can be uploaded to it.

   .. NOTE::
      If indirect_url is specified it will always be used, even if the form parameter *build* is also provided in the
      same request.

   **Example request (direct)**:

   .. sourcecode:: bash

      $ curl -XPOST '/app/widgetmakers/builds/1-master?file_type=zip' -F "build=@/home/user/build.zip"

   **Example request (indirect)**:

   .. sourcecode:: bash

      # indirect upload from http://foobar.com/build.zip
      $ curl -XPOST '/app/widgetmakers/builds/1-master?file_type=zip&indirect_url=http%3A%2F%2Ffoobar.com%2Fbuild.zip'


Delete Build
^^^^^^^^^^^^

.. http:delete::   /app/(string: app_name)/builds/(string: build_name)

   Remove a build object. This will delete all uploaded data associated with this object.

   **Example request**:

   .. sourcecode:: bash

      $ curl -XDELETE '/app/widgetmakers/builds/1-master'


Packagemaps
-----------

View Package Maps
^^^^^^^^^^^^^^^^^

.. http:get::       /app/(string: app_name)/packagemaps

   View all package maps associated with the application.

   **Example request**:

   .. sourcecode:: bash

      $ http GET '/app/widgetmakers/packagemaps'


View Package Map
^^^^^^^^^^^^^^^^

.. http:get::       /app/(string: app_name)/packagemaps/(string: packagemap_name)

   View individual package map.

   **Example request**:

   .. sourcecode:: bash

      $ http GET '/app/widgetmakers/packagemaps/my_package_map'


Create Package Map
^^^^^^^^^^^^^^^^^^

.. http:put::   /app/(string: app_name)/packagemaps

   :param name: package map name
   :type name: string
   :jsonparam string body: JSON object containing package map

   Create a new package map.

   A package map is a mapping of package names to one or more filename patterns. Patterns are interpreted as glob expressions
   including '**' syntax for recursive matching (similar to globstar option of the bash shell). Each package must have a
   "patterns" key consisting of a list of one or more pattern strings.

   There can be any number of packages within the package map, and there must be at least one pattern associated with each package.

   **Package Map Format**

   A package map is a mapping of package name (which can be an arbitrary string) to a JSON object consisting of the
   following fields:

   - *patterns* (required, list of strings): a list of glob-style patterns which will be matched against
     filenames (including paths) in the master package. Matching files will be included in the package. "**" (double
     star) may be used for recursive matching.
   - *prefix* (optional, string): this string will be prepended to the archive name of each file in the package. Path
     separators can be used to create a directory hierarchy. This is performed after remove_prefix is processed (if
     present).
   - *remove_prefix* (optional, string): if this string is present in the filename (including path), it will be removed
     exactly once beginning from the left. Prefix removal always occurs prior to prefix prepending via the "prefix" field.


   **Example JSON body**

   .. sourcecode:: json

      {
        "packages": {

           "binaries": {
               "patterns": [ "bin/**/*" ]
           },
           "configs": {
               "patterns": [ "conf/**/*.xml" ],
               "prefix": "app-config/"
           }

        }
      }

   The above package map creates two packages: "binaries" and "configs". The first ("binaries") contains all files in
   the top-level "bin/" directory within the master package. The files are added recursively preserving directory structure.

   The second package ("configs") includes all XML files under the top-level "conf/" directory within the master package.
   Note that it also preserves the directory structure (but directories that do not contain matching files will not be included).

   Note also that the "configs" package contains a prefix field. The prefix will be prepended to the archive name of every
   file in the package. For example, if a file "conf/a/b/main.xml" is added to the package, the archive name (the name that
   the file will have when the package is unpacked) will be "app-config/conf/a/b/main.xml". There is another optional field
   called "remove_prefix" which does the opposite: if that string is present in the filename, it will be removed a maximum
   of one time starting from the left.

   **Example request**:

   .. sourcecode:: bash

      $ echo '{ "packages": { "binaries": { "patterns": [ "bin/**/*" ] } } }' |http PUT '/app/widgetmakers/packagemaps?name=example_map'


Delete Package Map
^^^^^^^^^^^^^^^^^^

.. http:delete::   /app/(string: app_name)/packagemaps/(string: map_name)

   Remove a package map.

   **Example request**:

   .. sourcecode:: bash

      $ http DELETE '/app/widgetmakers/packagemaps/example_map'


Gitrepos
--------

View Gitrepos
^^^^^^^^^^^^^

.. http:get::   /app/(string: app_name)/gitrepos

   View gitrepos.


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/app/widgetmakers/gitrepos'


View Gitrepo
^^^^^^^^^^^^

.. http:get::   /app/(string: app_name)/gitrepos/(string: gitrepo_name)

   View individual gitrepo.


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/app/widgetmakers/gitrepos/MyRepo1'


Create Gitrepo
^^^^^^^^^^^^^^

.. http:put::   /app/(string: app_name)/gitrepo

   :param name: repository name
   :type name: string
   :param existing: does repository currently exist?
   :type existing: boolean ("true"/"false")
   :param gitprovider: name of gitprovider
   :type gitprovider: string
   :param keypair: name of keypair
   :type keypair: string


   Create a new gitrepo. If the parameter "existing" is false, Elita will create the repository using the gitprovider
   API.

   **Example request**:

   .. sourcecode:: bash

      $ curl -XPUT '/app/widgetmakers/gitrepos?name=MyRepo1&existing=false&gitprovider=gp1&keypair=kp1'


Delete Gitrepo
^^^^^^^^^^^^^^

.. http:delete::   /app/(string: app_name)/gitrepos/(string: gitrepo_name)

   Remove a gitrepo object. This will *not* delete the underlying repository from the gitprovider.

   **Example request**:

   .. sourcecode:: bash

      $ curl -XDELETE '/app/widgetmakers/gitrepos/MyRepo1'


Gitdeploys
----------

.. _gitdeploy-endpoints:

View Gitdeploys
^^^^^^^^^^^^^^^

.. http:get::   /app/(string: app_name)/gitdeploys

   View gitdeploys.


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/app/widgetmakers/gitdeploys'


View Gitdeploy
^^^^^^^^^^^^^^

.. http:get::   /app/(string: app_name)/gitdeploys/(string: gitdeploy_name)

   View individual gitdeploy.


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/app/widgetmakers/gitdeploys/WebApplication'


Create Gitdeploy
^^^^^^^^^^^^^^^^

.. http:put::   /app/(string: app_name)/gitdeploys

   :param name: gitdeploy name
   :type name: string
   :jsonparam string body: JSON object containing gitdeploy object

   Create a new gitdeploy. You must provide a valid JSON-encoded gitdeploy object in the body of the request.

   The *required* top-level keys are:
        "package" - the build package to deploy. Must be a string and must be a valid package name. Note that this
        is *not* checked for validity at the time of gitdeploy creation, allowing you to create gitdeploys prior to
        implementing packaging.

        "location" - an object describing where to deploy on end servers (see below)

   Additional *optional* top-level keys are:
        "attributes" - user-defined attributes

        "options" - git options (see below)

        "action" - pre/post salt states to run in addition to the deployment (see below)

   Location object:
        The location object is a JSON object that has the following required keys:

        "path" - absolute deployment path on end servers. This is where the gitrepo will be cloned.

        "gitrepo" - name of gitrepo to deploy at *path*.

        "default_branch" - name of git branch to deploy (use 'master' unless you know you need something else)

   Options object:
        The options object allow you to specify the following git options which are used during deployments:

        "favor" - can be "ours" (local) or "theirs" (remote). Defaults to "ours". This reduces the chances of merge
        failures if local changes exist, preferring the local changes to the incoming remote changes.

        "ignore-whitespace" - "true"/"false". Also reduces likelihood of merge conflicts. Defaults to true.

        "gitignore" - a list of strings representing the .gitignore file *on end servers*. Use this to ignore
        local changes on end servers so they don't cause failed deployments.

   Actions object:
        The actions object allows you to inject salt states into the gitdeploy. It consists of two keys: "prepull"
        and "postpull". As the names suggest, "prepull" is executed immediately prior to deployment and "postpull" is
        executed immediately afterward.

        Salt states by convention are usually expressed as YAML. This is easily translated into JSON. Keep in mind,
        however, that every state must have a unique ID. It's therefore preferable to express them with an arbitrary
        (but unique) ID and an explicit "name" parameter, rather than the more terse form of using the ID as the implicit
        name.

        *Example*:

            This is an idiomatic Salt state to ensure httpd is running (in YAML):
                .. sourcecode:: yaml

                   httpd:
                        service
                        - running

            Prior to injection it should be converted to the following form (in YAML):
                .. sourcecode:: yaml

                   start_apache:
                        service:
                        - name: httpd
                        - running

            Translated into JSON:
                .. sourcecode:: json

                   {
                    "start_apache": {
                        "service": [
                            {
                                "name": "httpd"
                            },
                            "running"
                        ]
                    }
                   }

   **Example gitdeploy object (simple)**:

   .. sourcecode:: json

      {
        "package": "webapplication_pkg",
        "location": {
          "path": "/opt/widgetmaker",
          "default_branch": "master",
          "gitrepo": "wm_webapp_gitrepo"
        }
      }


   **Example gitdeploy object (complex)**:

   .. sourcecode:: json

      {
        "attributes": {
          "description": "Example gitdeploy for Elita documentation"
        },
        "package": "webapplication_pkg",
        "location": {
          "path": "/opt/widgetmaker",
          "default_branch": "master",
          "gitrepo": "wm_webapp_gitrepo"
        },
        "options": {
          "favor": "ours",
          "ignore-whitespace": "true",
          "gitignore": [
            "foo.txt"
          ]
        },
        "actions": {
          "prepull": {
            "stop_apache": {
              "service": [
                {
                  "name": "httpd"
                },
                "dead"
              ]
            }
          },
          "postpull": {
            "start_apache": {
              "service": [
                {
                  "name": "httpd"
                },
                "running"
              ]
            }
          }
        }
      }

   **Example request**:

   .. sourcecode:: bash

      $ curl -XPUT '/app/widgetmakers/gitdeploys?name=WebApp' -d $(cat WebApp.json)


Initialize/Deinitialize Gitdeploy
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. http:post::   /app/(string: app_name)/gitdeploy/(string: gitdeploy_name)

   :param initialize: initialize gitdeploy
   :type initialize: boolean ("true"/"false")
   :param deinitialize: deinitialize gitdeploy
   :type deinitialize: boolean ("true"/"false")
   :jsonparam string body: JSON object containing the list of servers to initialize/deinitialize

   Initializes (or deinitializes) a gitdeploy from one or more servers.

   "Initializing" is the act of copying required keypairs, setting them up and cloning the gitrepo at the specified
   path. A server must have a gitdeploy initialized on it before deployments to that server can be performed.

   "Deinitializing" is the act of deleting keypairs and the gitrepo from the target servers.

   .. ATTENTION::
      The parent of "path" must exist. For example, if the gitdeploy path is /opt/applications/MyApp, the directory
      /opt/applications must exist. The subfolder MyApp will be created as part of the clone operation.

   Servers object:
      This must have a "servers" key that is a list of servers to apply the initialization/deinitialization to.

      *Example:*

      .. sourcecode:: json

         {
            "servers": [ "web01", "web02", "web03" ]
         }

   **Example request (initialize)**:

   .. sourcecode:: bash

      $ curl -XPOST '/app/widgetmakers/gitdeploys/WebApp?initialize=true' -d '{ "servers": [ "web01" ] }'

   **Example request (deinitialize)**:

   .. sourcecode:: bash

      $ curl -XPOST '/app/widgetmakers/gitdeploys/WebApp?deinitialize=true' -d '{ "servers": [ "web01" ] }'


Delete Gitdeploy
^^^^^^^^^^^^^^^^

.. http:delete::   /app/(string: app_name)/gitdeploys/(string: gitdeploy_name)

   Remove a gitdeploy object.

   **Example request**:

   .. sourcecode:: bash

      $ curl -XDELETE '/app/widgetmakers/gitdeploys/WebApp'


Groups
------

Application groups are logical groups of gitdeploys. Groups are used to combine gitdeploys into logical units in various
ways--for example, different groups can share common gitdeploys. Server group membership is calculated
dynamically based on what gitdeploys are initialized on the servers.


View Groups
^^^^^^^^^^^

.. http:get::   /app/(string: app_name)/groups

   View groups.


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/app/widgetmakers/groups'


View Group
^^^^^^^^^^

.. http:get::   /app/(string: app_name)/groups/(string: group_name)

   :param environemnts: (optional) filter by list of environments
   :type name: string (space-delimited list of environment names)

   View individual group. If *environments* is specified, the servers listed will be filtered by the environments
   specified (will return servers present in *any* of the environments passed).

   The server list returned is dynamically calculated based on the gitdeploys initialized on servers at the time the
   request is made.


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/app/widgetmakers/groups/WebFrontEnd?environments=production+testing'


Create Group
^^^^^^^^^^^^

.. http:put::   /app/(string: app_name)/groups

   :param name: group name
   :type name: string
   :param rolling_deploy: (optional) group requires a rolling (batched) deployment. Defaults to false.
   :type rolling_deploy: boolean ("true"/"false")
   :jsonparam string body: JSON object containing list of gitdeploys

   Create a group. You must supply a JSON-encoded list of gitdeploys in the body of the request. The "gitdeploys" key
   can either be a flat list of strings (unordered) or a list-of-lists (ordered). See :ref:`Group Explanation <group-explanation>`
   for details.

   *Example JSON*:

   .. sourcecode:: json

      {
        "gitdeploys": [ "Configuration", "WebApplication", "StaticAssets" ]
      }

   **Example request**:

   .. sourcecode:: bash

      $ curl -XPUT '/app/widgetmakers/groups?name=WebFrontEnd' -d '{ "gitdeploys": [ "Configuration", "WebApplication", "StaticAssets" ] }'


Delete Group
^^^^^^^^^^^^

.. http:delete::   /app/(string: app_name)/groups/(string: group_name)

   Remove a group object.

   **Example request**:

   .. sourcecode:: bash

      $ curl -XDELETE '/app/widgetmakers/groups/WebFrontEnd'


Deployments
-----------

Deployment endpoints allow you to push builds to servers/gitdeploys ("manual deployment") or environments/groups ("group
deployment"). For details about the backend mechanism, see: :ref:`Gitdeploy Explanation <gitdeploy-explanation>`

View Deployments
^^^^^^^^^^^^^^^^

.. http:get::   /app/(string: app_name)/deployments

   View all deployments (by id).


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/app/widgetmakers/deployments'


View Deployment
^^^^^^^^^^^^^^^

.. http:get::   /app/(string: app_name)/deployments/(string: deployment_id)

   View deployment detail.


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/app/widgetmakers/deployments/53716bfddf15e00e19043b8f'


Execute Deployment
^^^^^^^^^^^^^^^^^^

.. http:post::   /app/(string: app_name)/deployments

   :param build_name: name of build to deploy
   :type build_name: string
   :param rolling_divisor: (optional) divisor for calculating rolling batches ("split into N batches"). Default is 2.
   :type rolling_divisor: positive integer
   :param rolling_pause: (optional) pause for N seconds between rolling batches. Default is 15.
   :type rolling_pause: positive integer
   :param ordered_pause: (optional) pause for N seconds between ordered gitdeploy batches. Default is 15.
   :type ordered_pause: positive integer
   :jsonparam string body: JSON object containing deployment target specification

   Perform a deployment.

   There are two general 'styles' of deployment: *manual deployment* and *group deployment*.

   A *manual deployment* is one in which you specify the individual servers and gitdeploys to which you want to deploy
   the build. This gives you the most flexibility but is also the most verbose. It also does not allow for automatic rolling
   deployments.

   A *group deployment* is one in which you specify only the *environment(s)* and the *group(s)* to deploy to. Elita will
   calculate the servers and gitdeploys that satisfy both specifications and--if the relevant groups require it--
   will perform an automatic batched rolling deploy.

   **Pause Options**

   The "rolling_pause" parameter is the number of seconds to wait between batches (the total number of servers split using
   the rolling_divisor parameter). If any groups contain ordered gitdeploys, the batches will be further split into batches
   to enforce the ordering.

   For example, if rolling_divisor is two (2), without ordering the servers would be split into two evenly sized batches.
   If each group had a set of two ordered gitdeploys, the servers would be split into four (4) batches. Batches 1 and 3
   would be "ordered" batches and, after complete, would result in a pause of ordered_pause seconds. Batch 2 would result
   in a rolling_pause (batch 4 is last and so would not have any pause afterward).

   **Example request (manual)**:

   .. sourcecode:: bash

      $ curl -XPOST '/app/widgetmakers/deployments?build_name=5-master' -d '{ "servers": [ "web01" ], "gitdeploys":
       [ "WebApplication", "Configuration" ] }'


   **Example request (group)**:

   .. sourcecode:: bash

      $ curl -XPOST '/app/widgetmakers/deployments?build_name=5-master&rolling_divisor=4' -d '{ "environments": [ "production" ],
      "groups": [ "WebFrontEnd" ] }'

