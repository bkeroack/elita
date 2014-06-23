===============
Getting Started
===============

First make sure Elita is :ref:`properly installed <elita-install>`.

This might seem like a lot of steps, but most of these steps only have to be done once. Only the final two need to
be done repeatedly (but you'll probably do the first at least automatically in your CI).

.. contents:: Contents

Log in
^^^^^^

.. sourcecode:: bash

   $ curl -XGET 'http://localhost:2718/global/users/admin?password=elita&pretty=true'


Will give you the following output:

.. sourcecode:: json

   {
    "status": "ok",
    "message": {
        "username": "admin",
        "attributes": {},
        "auth_token": [
            "OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng"
        ],
        "permissions": {
            "apps": {
                "*": "read/write",
                "_global": "read/write"
            },
            "actions": {
                "*": {
                    "*": "execute"
                }
            },
            "servers": [
                "*"
            ]
        }
     }
   }

The *auth_token* field is the only thing you need to care about. Copy it down because you'll need it for nearly every subsequent
request. You can pass the auth token as a header (like we do below) or as the URL parameter *auth_token*.


Create Application
^^^^^^^^^^^^^^^^^^

Applications provide separate namespaces for the child endpoints (gitrepos, gitdeploys, deployments, etc). In general,
you should create a separate application for each top-level project in your continuous integration environment. If your
project has multiple deployables (subapplications) they can be deployed as separate groups under a single application.

(Splitting between groups and applications is somewhat arbitrary--but since builds are created per-application, generally
anything that is built together should go into a single application. Use groups to distinguish between different binaries
built together.)

.. sourcecode:: bash

   $ curl -XPUT 'http://localhost:2718/app?app_name=testapp&pretty=true' -H
   'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'



Create Server(s)
^^^^^^^^^^^^^^^^

Pick an environment name ("prod", "qa", etc) and create your server objects. Keep in mind that Elita environments
are completely separate from salt environments. Use them as tags to group your servers logically.

Always use "existing=true". This may change if/when server provisioning is implemented in Elita.

.. sourcecode:: bash

   $ curl -XPUT 'http://localhost:2718/server?name=server01&environment=prod&existing=true&pretty=true' -H
   'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'


Create Gitprovider
^^^^^^^^^^^^^^^^^^

Use your BitBucket credentials to create a gitprovider. It might be smart to create a separate BitBucket account, since
this will only be used to manage deployment repositories. In the body of the request, pass a JSON object containing type
and authentication information.

At this point it should be obvious that since authentication information (and, in the next step, key data) is stored
in MongoDB, that database should be protected from unauthorized access.

.. sourcecode:: bash

   $ curl -XPUT 'http://localhost:2718/global/gitproviders?name=gp1&pretty=true' -d '{
   "type": "bitbucket", "auth": { "username": "myusername", "password": "passw0rd" } }' -H
   'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'


Create Keypair
^^^^^^^^^^^^^^

Upload an SSH keypair that has read/write access to deployment repositories created by the gitprovider above. You should
probably create a new keypair and register it under the BitBucket account above.

There are two ways to upload: either JSON-encoded key data in a PUT request, or file data in a POST request. The latter
is generally more convenient.

.. sourcecode:: bash

   $ curl -XPOST 'http://localhost:2718/global/keypairs?type=git&name=kp1&from=files&pretty=true' -F "private_key=@/home/user/keys/mykey"
   -F "public_key=@/home/user/keys/mykey.pub" -H
   'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'


Create Gitrepo
^^^^^^^^^^^^^^

Now you can create your first gitrepo. This will be created by Elita if it does not exist under the gitprovider's
BitBucket account. This repository will be used as a deployment repository to transfer build data from Elita to your
servers. All gitrepos should be private.

(Note that REST semantics are violated slightly here since this a PUT request that can trigger a non-idempotent action
[repository creation]. Just remember that if existing=false, the repo will be created)

.. sourcecode:: bash

   $ curl -XPUT 'http://localhost:2718/app/testapp/gitrepos?name=repo1&existing=false&gitprovider=gp1&keypair=kp1&pretty=true'
   -H 'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'


Create Gitdeploy
^^^^^^^^^^^^^^^^

This is the most powerful (and complex) object in Elita. Fundamentally, a gitdeploy is a mapping of a package (within a build)
to a filesystem location on servers (ex: ``/opt/application`` or ``C:\MyApplication``). You can also include salt states
that will be executed before and after deployments, custom git options, gitignore entries, etc.

Keep in mind that a server can have any number of gitdeploys on it, in whatever location scheme works best for you. You
could have a gitdeploy for application binaries, another for configuration data, a third for static assets, etc. You
could even set up salt states to create symlinks between the various gitdeploys if that is what your deployment setup
requires.

In the request body provide a JSON object specifying at least "package" and "location", where "location" contains the three
keys: "path" (location on server), "gitrepo" (name of gitrepo to deploy here), "default_branch" (branch of gitrepo to check out).
"package" is the build package ("master" by default, which is equivalent to the uploaded build verbatim).

.. sourcecode:: bash

   $ curl -XPUT 'http://localhost:2718/app/testapp/gitdeploys?name=FirstGitdeploy&pretty=true' -d '{
    "package": "master", "location": { "path": "/opt/app", "gitrepo": "repo1", "default_branch": "master" } }'
   -H 'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'


Initialize Gitdeploy on Servers
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Now we need to set up the keys and clone the initial repository state on the target servers. Do this with a POST
request on the gitdeploy object. In the request body pass a JSON object with a "servers" key which is a list of servers
to initialize.

.. sourcecode:: bash

   $ curl -XPOST 'http://localhost:2718/app/testapp/gitdeploys/FirstGitdeploy?&initialize=true&pretty=true' -d '{
    "servers": [ "server1" ] }'
   -H 'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'

The initialization will be done asynchronously. If you take the *job_id* returned from the request and query it as a
job object you can check progress:

.. sourcecode:: bash

   $ curl -XGET 'http://localhost:2718/job/36cf2f16-9c2f-43eb-a6e3-ef65e4d50e1f?results=true&pretty=true'

(Job objects are one of the few objects that can be queried without Auth-Token.)


(optional) Create Application Group
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Application groups are ways to group multiple gitdeploys into a logical "subapplication". For example, if your main
application codebase contains both frontend servers and backend worker nodes, you could create two groups with the
gitdeploys for each ("Frontend", "Workers").

Application groups allow you to organize and slice your servers/deployments two-dimensionally: by environment and by group.
This allows you do more intuitive deployment calls (by group and environment) rather than by servers and gitdeploys, and
allows for automatic rolling deployments without downtime.

On the other hand, for simple installations (or if you only have one gitdeploy) it may not make sense to use groups.

.. sourcecode:: bash

   $ curl -XPUT 'http://localhost:2718/app/testapp/groups?&name=MainGroup&rolling_deploy=true&pretty=true' -d '{
    "gitdeploys": [ "FirstGitdeploy", "SecondGitdeploy" ] }'
   -H 'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'


Create/Upload Build
^^^^^^^^^^^^^^^^^^^

At this point you're ready to create and upload your first application build.

Create the build object:

.. sourcecode:: bash

   $ curl -XPUT 'http://localhost:2718/app/testapp/builds?build_name=1-master&pretty=true'
   -H 'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'

Now you have to upload the build data itself. This should be automated as part of your CI workflow (indeed, that's the
whole point of Elita!) but for testing purposes you can do this manually as well.

Elita requires your build to be in an archive of some sort (ZIP, gzip/bzip2 tarball). You can either upload directly as
POST filedata or indirectly by providing a URL that Elita can download the build from (which could be S3 or some other
storage service, or even another Elita server!).

For a direct upload:

.. sourcecode:: bash

   $ curl -XPOST 'http://localhost:2718/app/testapp/builds/1-master?file_type=zip&pretty=true'
   -F "build=@/home/user/build.zip"
   -H 'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'

For an indirect upload from https://foobar.com/build.zip:

.. sourcecode:: bash

   $ curl -XPOST 'http://localhost:2718/app/testapp/builds/1-master?file_type=zip&pretty=true&indirect_url=https%3A%2F%2Ffoobar.com%2Fbuild.zip'
   -H 'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'

Indirect upload (and file integrity verification) is done asynchronously and will return a *job_id*.

After the upload completes, a hook will be triggered that allows plugins to repackage builds. By default (without plugins)
the only package available will be "master", which corresponds to the file that was uploaded. (PLANNED FOR THE FUTURE:
"package_map" feature which allows repackaging without plugins)


Deploy Build
^^^^^^^^^^^^

Finally you can deploy your build *1-master* to your servers. This is done via a POST request to the deployments
container. In the request body, provide a JSON object that specifies **either** the servers/gitdeploys to deploy to
**or** the groups/environments. If you specify groups/environments and one or more groups has the *rolling_deploy* flag set
to true, a rolling deployment will be performed. You can control the number of batches with the URL parameter *rolling_divisor*
and the delay between batches with *rolling_pause*.

.. sourcecode:: bash

   $ curl -XPOST 'http://localhost:2718/app/testapp/deployments?build_name=1-master&pretty=true' -d '{
   "servers": [ "server01" ], "gitdeploys": [ "FirstGitdeploy" ] }'
   -H 'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'

As always, the operation is performed asynchronously and a *job_id* is returned. Poll the job object to monitor progress.


Going forward...
^^^^^^^^^^^^^^^^

The above is a walkthrough of some of the most basic functionality available with Elita. Keep in mind the codebase is beta,
the API may change and more features are in the planning stages. Please file bugs if you run into any trouble or if you
have any suggestions for improvement.

Thanks for reading!
