================
Global Endpoints
================
(only supported verbs are shown for each endpoint)

.. contents:: Contents

Users
-----

View Users
^^^^^^^^^^

.. http:get::   /global/users

   Returns terse list of users


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/global/users'

   **Example response**

   .. sourcecode:: json

      {
          "users": [
              "admin",
              "robert",
              "mary",
              "john"
          ]
      }

.. http:get::   /global/users/(string:username)

   Get a user and create and return an auth token (if necessary). This will create a new auth token if one does not
   currently exist.

   This can be considered the equivalent to "logging in".

   :param password: Password (URL-encoded if necessary)
   :param auth_token: Auth token (only if password is not provided)
   :type password: string
   :type auth_token: string

   **Example request**

   .. sourcecode:: bash

      $ curl -XGET '/global/users/joe?password=1234'

   **Example response**

   .. sourcecode:: json

      {
          "status": "ok",
          "message": {
              "username": "joe",
              "attributes": {},
              "auth_token": [
                  "NWFjNzkwNWQ4MjQyNzY5MWJjMjVlOTE4ODMwM2E1M2EyMzBiZDIyMFjNzkwNWQ4MjQyNzY5MWJjMjVlOTE4ODMQ"
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
                  "servers": "*"
               }
          }
      }


View Computed User Permissions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. http:get::   /global/users/(string:username)/permissions

   Get all current applications, actions and servers the user has permissions to access,
   computed according to the permissions object associated with the user.

   **Example request**

   .. sourcecode:: bash

      $ curl -XGET '/global/users/joe/permissions'

   **Example response**

   .. sourcecode:: json

      {
            "username": "joe",
            "applications": {
                "read/write": [
                    "widgetmaker",
                    "widget2"
                ],
                "read": [
                    "_global"
                ]
            },
            "actions": {
                "widgetmaker": [
                    "ExampleAction",
                    "SpecialDeploymentAction",
                    "CleanupBuilds"
                ]
            },
            "servers": [
                "server01",
                "server02"
            ]
      }


Create User
^^^^^^^^^^^

.. http:put:: /global/users

   Creates a new user or modifies an existing user.

   :param username: Username (URL-encoded)
   :param password: Password (URL-encoded, optional with auth_token)
   :param auth_token: Auth token (optional if password provided)
   :jsonparam string body: JSON object containing permissions object and optional attributes object.
   :type username: string
   :type password: string
   :type auth_token: string

   **Permissions JSON object**

   The permissions JSON object consists of three name/value pairs: apps, actions, servers.

   The "apps" value consists of one subobject with an arbitrary number of name/value pairs.
   The name is treated as a glob pattern matching against application names. The value is the permissions to grant
   applications which match the pattern. Valid permissions are "read" and "write" (delimited with '/' for both).
   Note that order is not significant ("read/write" is the same as "write/read") and the '/' delimiter is
   simple convention. Only the existence of "read" and "write" substrings are checked,
   so "read;write" would work equally well.

   .. NOTE::
      There exists a special application named '_global'. This represents access to all administrative containers/endpoints
      including nearly everythign under /global (with the exception of individual user objects, which can be accessed
      by simple password auth, and tokens which are permissionless) as well as the jobs container (but not individual jobs).

   "read" allows access to the GET verb for all endpoints associated with that application while "write" allows
   access to all verbs which change state (PUT, POST, PATCH, DELETE).

   The "actions" value contains an object with an arbitrary number of nested subobjects,
   each treated as a glob pattern matching application names. The value associated with any pattern is a subobject
   with the names treated as glob patterns matching action names of that application. Finally,
   the value associated with the action glob is tested for the substring "execute". If it exists,
   permission is granted to execute that action. If it does not, permission is denied. Execute permission allows
   access to all verbs for that action.

   .. NOTE::
      Conflicting permissions statements have undefined behavior (it depends upon the order of evaluation which
      is not guaranteed).

   The "servers" value consists of a simple list of glob patterns which match server names. The user will be
   granted full permission to any servers matching any of the patterns.

   **Example request**

   .. sourcecode:: bash

      $ curl -XPOST '/global/users?username=joe&password=1234' -d '
      {
        "attributes": {
            "address": "123 Spring Street, Knoxville, TN 012345"
         },
         "permissions": {
            "apps": {
                "*": "read/write",
                "newapp": ""
            },
            "actions" {
                "newapp": {
                    "ScriptedAction": "execute"
                },
                "otherapp": {
                    "*": "execute"
                }
            },
            "servers": []
         }
      }'

   This grants the following permissions:

* Give user read/write access to all applications EXCEPT newapp
* Give execute permission to "ScriptedAction" only under newapp
* Give execute permission to all actions under otherapp
* Do not give any permissions to any servers


Modify User
^^^^^^^^^^^

.. http:patch::   /global/users/(string:username)

   Modify a user. On the fields specified in the JSON body will be altered.

   :param password: Password (URL-encoded if necessary)
   :param auth_token: Auth token (only if password is not provided)
   :jsonparam string body: JSON object containing user fields to modify
   :type password: string
   :type auth_token: string

   **Example request**

   .. sourcecode:: bash

      $ curl -XPATCH '/global/users/joe?password=1234' -d '{ "attributes": { "nickname": "joey" } }'

   **Example response**

   .. sourcecode:: json

      {
          "status": "ok",
          "message": {
              "username": "joe",
              "attributes": {
                "nickname": "joey"
              },
              "auth_token": [
                  "NWFjNzkwNWQ4MjQyNzY5MWJjMjVlOTE4ODMwM2E1M2EyMzBiZDIyMFjNzkwNWQ4MjQyNzY5MWJjMjVlOTE4ODMQ"
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
                  "servers": ["*"]
               }
          }
      }


Delete User
^^^^^^^^^^^

.. http:delete::    /global/users/(string:username)

   Delete a user.

   .. NOTE::
      You can use either password authentication or auth token.

   :param password: Password (URL-encoded, optional with auth_token)
   :param auth_token: Auth token (optional if password provided)
   :type password: string
   :type auth_token: string

   **Example request**

   .. sourcecode:: bash

      $ curl -XDELETE '/global/users/joe'


Tokens
------

View Tokens
^^^^^^^^^^^

.. http:get::   /global/tokens

   Get list of issued auth tokens. This requires '_global' permissions to view.

   **Example request**

   .. sourcecode:: bash

      $ curl -XGET '/global/tokens'


View Token
^^^^^^^^^^

.. http:get::   /global/tokens/(string:token)

   Get information about token (associated user and time of issuance).

   .. NOTE::
      This endpoint does not require authentication. The token is the secret.

   **Example request**

   .. sourcecode:: bash

      $ curl -XGET
      '/global/tokens/NWFoNzkwNWQ4M2QyNzY5MWJjMjVlJdu7ODMwM2E1M2EyMzBiZDIyMmMyMGE9Idjn4Yzg2ZjYwODQ1ZWYyNTVmM9'


Delete Token
^^^^^^^^^^^^

.. http:delete::   /global/tokens/(string:token)

   Delete an auth token. This is the equivalent of "logging out".

   .. NOTE::
      This endpoint does not require authentication. The token is the secret.

   **Example request**

   .. sourcecode:: bash

      $ curl -XDELETE
      '/global/tokens/NWFoNzkwNWQ4M2QyNzY5MWJjMjVlJdu7ODMwM2E1M2EyMzBiZDIyMmMyMGE9Idjn4Yzg2ZjYwODQ1ZWYyNTVmM9'

Gitproviders
------------

View Gitproviders
^^^^^^^^^^^^^^^^^

.. http:get::   /global/gitproviders

   Get list of gitproviders.

   **Example request**

   .. sourcecode:: bash

      $ curl -XGET '/global/gitproviders'


.. http:get::   /global/gitproviders/(string:gitprovider)

   Get information about a gitprovider.

   **Example request**

   .. sourcecode:: bash

      $ curl -XGET '/global/gitproviders/mygitprovider'


Create Gitprovider
^^^^^^^^^^^^^^^^^^

.. http:put::   /global/gitproviders

   :param name: gitprovider name
   :jsonparam string body: JSON object containing gitprovider description
   :type name: string

   Create new gitprovider.

   **Example JSON body**

   .. sourcecode:: json

      {
          "type": "bitbucket",
          "auth": {
            "username": "my-username",
            "password": "password1234"
          }
      }

   **Example request**

   .. sourcecode:: bash

      $ curl -XPUT '/global/gitproviders?name=mygitprovider' -d '{
          "type": "bitbucket",
          "auth": {
            "username": "my-username",
            "password": "password1234"
          }
      }'


Modify Gitprovider
^^^^^^^^^^^^^^^^^^

.. http:patch::   /global/gitproviders/(string:gitprovider)

   :jsonparam string body: JSON object containing gitprovider fields to modify

   Modify gitprovider. Only fields provided in JSON body will be changed.

   .. NOTE::
      The only valid field to modify is "auth".

   **Example request**

   .. sourcecode:: bash

      $ curl -XPATCH '/global/gitproviders/mygitprovider' -d '{ "auth": {
            "username": "my-username",
            "password": "password1234"
          }
       }'

Delete Gitprovider
^^^^^^^^^^^^^^^^^^

.. http:delete::   /global/gitproviders/(string:gitprovider)

   Remove gitprovider.

   **Example request**

   .. sourcecode:: bash

      $ curl -XGET '/global/gitproviders/mygitprovider'

Keypairs
--------

View Keypairs
^^^^^^^^^^^^^

.. http:get::   /global/keypairs

   Get list of keypairs.

   **Example request**

   .. sourcecode:: bash

      $ curl -XGET '/global/keypairs'


.. http:get::   /global/keypairs/(string:keypair)

   Get information about a keypair.

   **Example request**

   .. sourcecode:: bash

      $ curl -XGET '/global/keypairs/mykeypair'


Create Keypair
^^^^^^^^^^^^^^

Keypairs can be uploaded either as JSON-encoded strings (PUT request) or as files (POST request).

.. http:put::   /global/keypairs

   :param name: keypair name (URL-encoded)
   :param type: keypair type ("git" or "salt")
   :param from: source of keypair data ("json" or "files")
   :jsonparam string body: (optional) JSON object containing JSON-encoded public and private keys
   :type name: string
   :type type: string
   :type from: string

   Create new keypair by providing JSON-formatted keys or by uploading key files directly. Both keys must be in SSH format.
   Use the URL parameter "from" to indicate which request is being made: "json" means the key data is JSON-encoded
   within the request body, "files" means the key files are provided as POST file data.

   **Example JSON body**

   .. NOTE::
      Key data omitted from examples.

   .. sourcecode:: bash

      {
          "private_key": "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n",
          "public_key": "ssh-rsa ... foo@bar.com\\n"
      }

   **Example request (JSON-encoded keys)**

   .. sourcecode:: bash

      $ curl -XPUT '/global/keypairs?type=git&name=mykeypair&from=json' -d '{
          "private_key": "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n",
          "public_key": "ssh-rsa ... foo@bar.com\\n"
      }'

   **Example request (key files)**

   .. sourcecode:: bash

      $ curl -XPUT '/global/keypairs?type=git&name=mykeypair&from=files' -F "private_key=@/path/to/private.key"
      -F "public_key=@/path/to/public.key"

.. http:post::   /global/keypairs

   :param name: keypair name (URL-encoded)
   :param type: keypair type ("git" or "salt")
   :formparameter private_key: private key file (ASCII)
   :formparameter public_key: public key file (ASCII
   :type name: string
   :type type: string

   Create new keypair by uploading key files.

   **Example request**

   .. sourcecode:: bash

      $ curl -XPOST '/global/keypairs?type=git&name=mykeypair' -F "private_key=@/home/user/keys/mykey"
      -F "public_key=@/home/user/keys/mykey.pub"


Modify Keypair
^^^^^^^^^^^^^^

.. http:patch::   /global/keypairs/(string:keypair)

   :jsonparam string body: JSON object containing key(s) to modify

   Modify keypair by replacing keys. Only keys provided in JSON body will be changed,
   but you will almost always want to specify both.

   **Example request**

   .. sourcecode:: bash

      $ curl -XPATCH '/global/keypairs/mykeypair' -d '{
          "private_key": "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n",
          "public_key": "ssh-rsa ... foo@bar.com\\n"
       }'


Delete Keypair
^^^^^^^^^^^^^^

.. http:delete::   /global/keypairs/(string:keypair)

   Remove keypair.

   **Example request**

   .. sourcecode:: bash

      $ curl -XDELETE '/global/keypair/mykeypair'

