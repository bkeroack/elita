
.. _gitdeploy-explanation:

==========
Gitdeploys
==========

For associated API endpoints, see: :ref:`Gitdeploy Endpoints <gitdeploy-endpoints>`

.. contents:: Contents

Introduction
------------

elita uses a mechanism based on git to push code and resources to servers called "gitdeploy".

This mechanism allows fast delta deployments. Only changed files are transmitted to servers,
and in fact only the deltas of changed files are transmitted, including for binary files. Git-based deployments are
suitable
and efficient both for textual applications (interpreted languages like Python) and compiled languages (native code
or bytecode applications like Java or .NET). The greatest efficiency gains tend to be with compiled applications,
since they often do not compress as well as text and have relatively small changes per revision (in terms of
bytes changed per binary file) and therefore can be transmitted very quickly.

As far as the API is concerned, a *gitdeploy* is an object (an API endpoint) which associates a git repository with a
location on one or more servers along with associated configuration options and attributes.

gitdeploy objects are created and then applied (initialized) to individual servers,
which creates the target directories and initializes the repositories. They can also be deinitialized
(deleted).

Deployments are executed in parallel across all target servers via salt.

.. NOTE::
   git can be inefficient for large binary files, typically over 150MB. If you have an application with
   individual files that exceed this approximate threshold, expect increased git metadata size or
   consider other deployment methodologies.


Build Packages
--------------

Elita allows for a build to have an arbitrary number of *packages* associated with it. A package is a way for you to
repackage or post-process the initial build artifacts into whatever form you need. For example,
you may have a monolithic sourcecode tree that contains a number of individual applications within it,
or you may want to repackage an application in different ways for different environments.

The default package is called "master" and is present on every uploaded build--it is identical to the originally
uploaded file. By default only the master package is present. You create subpackages by creating and using a
*package map* (see below).


Package Maps
------------

A package map is a mapping of package names to one or more filename patterns. Patterns are interpreted as glob expressions
including '**' syntax for recursive matching (similar to globstar option of the bash shell).

Example:

.. sourcecode:: json

   {
        "binaries": {
            "patterns": [ "bin/**/*" ]
        },
        "configs": {
            "patterns": [ "conf/**/*.xml" ],
            "prefix": "app-config"
        }
   }

The above package map creates two packages: "binaries" and "configs". The first ("binaries") contains all files in
 the top-level "bin/" directory within the master package. The files are added recursively preserving directory structure.

The second package ("configs") includes all XML files under the top-level "conf/" directory within the master package.
Note that it also preserves the directory structure (but directories that do not contain matching files will not be included).

Note also that the "configs" package contains a prefix field. The prefix will be prepended to the archive name of every
file in the package. For example, if a file "conf/a/b/main.xml" is added to the package, the archive name (the name that
the file will have when the package is unpacked) will be "app-config/conf/a/b/main.xml".

Package maps support any number of package definitions, and each package can have any number of patterns associated with
it (but must have at least one). Prefix is optional.


Backend Mechanism
-----------------

Elita performs the following steps when a deployment is triggered:

   #.   The specified *package* in the gitdeploy (defaults to master) associated with the *build* being deployed is
        decompressed to the repository working copy on the elita server.
   #.   If changes are detected, they are added and committed.
   #.   If there is a commit, the commit is pushed upstream to the gitprovider.
   #.   Any specified pre-pull salt states are executed on the target server(s).
   #.   A git pull is performed (along with any options) on the gitdeploy location on the target server(s).
   #.   Any specified post-pull salt states are executed on the target server(s).

.. NOTE::
   There are also various hook points during this process where custom routines from plugins can execute.


Local Changes
-------------

Gitdeploy allows for persistent local changes on end servers.

If you need to modify a file within a gitdeploy on a server (for example, if you need to change a configuration file
only on one server in a farm), this can be done by editing the file and then committing locally on that repository.
These changes will then persist with future deployments, as new code will be automatically merged into the existing
repository without overwriting local changes.

Any *uncommitted* changes will be lost with the next deployment to prevent pull failure.

.. CAUTION::
   Any time you modify a gitdeploy locally it creates a chance that future deployments could result in a merge error
   and failed deployment. Elita uses git options to minimize the changes of merge errors by default,
   but they can never be fully eliminated. Even when successful, any time an automatic merge happens there is a chance
   that the application could be changed in some undesired way.

.. WARNING::
   Do not push changes from end servers to the upstream gitprovider. By default, elita puts an invalid upstream URL
   to prevent accidental pushes.


API Objects
-----------

Follow is a list of the associated API objects (endpoints):

**server**

    A machine to which you want to deploy builds or apply actions. It is assumed that the server is addressable by
    name via salt--for a server named 'server01' you should be able to do ``salt 'server01' test.ping`` prior to creating
    the server object in Elita.

    Gitdeploys are initialized on servers, which pushes the appropriate SSH keys and clones the gitrepo at the
    configured path.

    Each server is associated with exactly one environment, which is a logical grouping of servers. A dynamically
    calculated environment roster can be obtained via GET on the /server/environments endpoint.

    .. NOTE::
       Elita environments are completely independent of salt environments.


**gitprovider**

    A provider of git repositories.

    Currently supported gitprovider types: BitBucket (GitHub is planned but not yet implemented)

    This object includes authentication information for an associated account and allows elita to create/delete/modify
    git repositories.


**keypair**

    A keypair is an SSH keypair that can be associated with one or more git repositories,
    used for authentication to push and pull data.


**gitrepo**

    A specific git repository, used to distribute code to servers. It is linked to a **gitprovider** and a **keypair**.


**gitdeploy**

    An object representing a mapping of a gitrepo to a path on one or more servers and associated configuration options.

    Example object (JSON):

    .. sourcecode:: http

       {
            "gitdeploy": {
                "name": "Widget",
                "package": "master",
                "attributes": { },
                "location": {
                    "path": "/opt/WidgetFactory",
                    "gitrepo": "Widget_MainRepo"
                    }
                },
                "options": {
                    "favor": "ours",
                    "ignore-whitespace": "true",
                    "gitignore": [
                        "app/foo.ignoreme",
                        "app/.DS_Store"
                    ]
                },
                "actions": {
                    "prepull": {},
                    "postpull": {}
                }
            }
       }

**group**

    A group (or application group) is a logical group of gitdeploys which make up a subapplication. For example a web
    application might have frontend web servers and backend workers, each requiring deployments of a different set of
    gitdeploys.

    Gitdeploys may overlap between groups. For example, given three gitdeploys (gitdeployA, gitdeployB, gitdeployC) the
    following groups could be constructed (not an exhaustive list, just an example):

    *   Group1:  gitdeployA, gitdeployB
    *   Group2:  gitdeployA, gitdeployC

    Any servers with the matching set of gitdeploys initialized on them are considered part of the group. Server group
    membership is dynamically calculated. You don't 'add' a server to a group, you create the group and any servers with
    the relevant gitdeploys automatically are considered members.


