==========
Gitdeploys
==========

elita uses a mechanism based on git to push code and resources to servers called "gitdeploy".

As far as the API is concerned, a *gitdeploy* is an object (an API endpoint) which associates a git repository with a
location on one or more servers along with associated configuration options and attributes.

gitdeploy objects are created and then applied (initialized) to individual servers,
which creates the target directories and initializes the repositories. They can also be deinitialized
(deleted).

This mechanism allows delta deployments. Only changed files are transmitted to servers,
and in fact only the deltas of changed files are transmitted, including for binary files. Git-based deployments are
suitable
and efficient both for textual applications (interpreted languages like Python) and compiled languages (native code
or bytecode applications like Java or .NET).

.. NOTE::
   git can be inefficient for large binary files, typically over 150MB. If you have an application with
   individual files that exceed this approximate threshold, expect increased git metadata size or
   consider other deployment methodologies.


=================
General Mechanism
=================

   #.   The specified *package* in the gitdeploy (defaults to master) associated with the *build* being deployed is
        decompressed to the central repository working copy on the elita server.
   #.   If changes are detected, they are added and committed.
   #.   If there is a commit, the commit is pushed upstream to the gitprovider.
   #.   Any specified pre-pull salt states are executed.
   #.   A git pull is performed (along with any options) on the gitdeploy location on the target server(s).
   #.   Any specified post-pull salt states are executed.

.. NOTE::
   There are also various hook points during this process where custom routines from plugins can execute.


===========
API Objects
===========

Follow is a list of the associated API objects (endpoints):


**gitprovider**

A provider of git repositories.

Currently supported gitprovider types: BitBucket, GitHub.

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
            "application": "WidgetApplication",
            "name": "Widget",
            "package": "master",
            "created_datetime": "2022-01-01 12:00:00+00:00",
            "attributes": { },
            "location": {
                "path": "/opt/WidgetFactory",
                "gitrepo": {
                    "gitprovider": {
                        "type": "bitbucket",
                        "name": "widget_bitbucket"
                    },
                    "name": "Widget_Main"
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
            },
            "servers": [
                "server001",
                "server002",
            ]
        }
   }


