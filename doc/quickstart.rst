===============
Getting Started
===============

First make sure Elita is :ref:`properly installed <elita-install>`.

Once you've verified it's working you can get started:

* create a user/login
* creating an application
* creating one or more servers
* creating a gitprovider
* uploading a keypair
* creating a gitrepo
* creating a gitdeploy
* creating a group
* creating/uploading a build
* finally, performing a deployment

It might seem like a lot of setup, but most of these steps only have to be done once. Only the final two need to
be done repeatedly (but you'll probably do the first at least automatically in your CI).

Log in
------

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

The *auth_token* field is the only thing you need to care about. Copy it down because you'll need it for every subsequent
request.


Create application
------------------

.. sourcecode:: bash

   $ curl -XPUT 'http://localhost:2718/app?app_name=testapp&pretty=true' -H
   'Auth-Token: OGNkODA4YzA1MTg5YjAwNWFlZGNhYzRhODZmOWNlMDI0OWM5OGM2YjhhNWM2Njc2ZTY5NjMxYjlhNTRkZDQ5Ng'

.. sourcecode:: json

   {
    "status": "ok",
    "action": {
        "new_application": {
            "name": "testapp"
        }
     }
   }
