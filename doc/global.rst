================
Global Endpoints
================
(only supported verbs are shown for each endpoint)

.. contents:: Contents

Users
-----

.. http:get::   /global/users

   Returns terse list of users


   **Example request**:

   .. sourcecode:: http

      $ curl -XGET '/global/users'

   **Example response**

   .. sourcecode:: http

      {
          "users": [
              "admin",
              "robert",
              "mary",
              "john"
          ]
      }

.. http:get::   /global/users/(string:username)

   Get a user and create and return an auth token (if necessary).
   This can be considered the equivalent to "logging in".

   :param password: Password (URL-encoded if necessary)
   :param auth_token: Auth token (only if password is not provided)
   :type password: string
   :type auth_token: string

   **Example request**

   .. sourcecode:: http

      $ curl -XGET '/global/users/joe?password=1234'

   **Example response**

   .. sourcecode:: http

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

.. http:patch::   /global/users/(string:username)

   Modify a user. On the fields specified in the JSON body will be altered.

   :param password: Password (URL-encoded if necessary)
   :param auth_token: Auth token (only if password is not provided)
   :jsonparam string body: JSON object containing user fields to modify
   :type password: string
   :type auth_token: string

   **Example request**

   .. sourcecode:: http

      $ curl -XPATCH '/global/users/joe?password=1234' -d '{ "attributes": { "nickname": "joey" } }'

   **Example response**

   .. sourcecode:: http

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
                  "servers": "*"
               }
          }
      }

.. http:put:: /global/users

   Creates a new user or modifies an existing user.

   :param username: Username (URL-encoded)
   :param password: Password (URL-encoded, optional with auth_token)
   :param auth_token: Auth token (optional if password provided)
   :jsonparam string body: JSON object containing permissions object and optional attributes object.
   :type username: string
   :type password: string
   :type auth_token: string

   **Example request**

   .. sourcecode:: http

      $ curl -XPOST '/global/users?username=joe&password=1234' -b '
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
            "servers": ""
         }
      }'

   This grants the following permissions:

* Give user read/write access to all applications EXCEPT newapp
* Give execute permission to "ScriptedAction" only under newapp
* Give execute permission to all actions under otherapp
* Do not give any permissions to any servers


.. http:delete::    /global/users/(string:username)

   Delete a user.

   .. NOTE::
      You can use either password authentication or auth token.

   :param password: Password (URL-encoded, optional with auth_token)
   :param auth_token: Auth token (optional if password provided)
   :type password: string
   :type auth_token: string

   **Example request**

   .. sourcecode:: http

      $ curl -XDELETE '/global/users/joe'

Tokens
------

.. http:get::   /global/tokens

   Get list of issued auth tokens

   **Example request**

   .. sourcecode:: http

      $ curl -XGET '/global/tokens'


.. http:get::   /global/tokens/(string:token)

   Get information about token (associated user and time of issuance).

   .. NOTE::
      This endpoint is auth-less. The token is the secret.

   **Example request**

   .. sourcecode:: http

      $ curl -XGET
      '/global/tokens/NWFoNzkwNWQ4M2QyNzY5MWJjMjVlJdu7ODMwM2E1M2EyMzBiZDIyMmMyMGE9Idjn4Yzg2ZjYwODQ1ZWYyNTVmM9'

.. http:delete::   /global/tokens/(string:token)

   Delete an auth token. This is the equivalent of "logging out".

   .. NOTE::
      This endpoint is auth-less. The token is the secret.

   **Example request**

   .. sourcecode:: http

      $ curl -XDELETE
      '/global/tokens/NWFoNzkwNWQ4M2QyNzY5MWJjMjVlJdu7ODMwM2E1M2EyMzBiZDIyMmMyMGE9Idjn4Yzg2ZjYwODQ1ZWYyNTVmM9'

Gitproviders
------------

.. http:get::   /global/gitproviders

   Get list of gitproviders.

   **Example request**

   .. sourcecode:: http

      $ curl -XGET '/global/gitproviders'


.. http:get::   /global/gitproviders/(string:gitprovider)

   Get information about a gitprovider.

   **Example request**

   .. sourcecode:: http

      $ curl -XGET '/global/gitproviders/mygitprovider'


.. http:put::   /global/gitproviders

   :param name: gitprovider name
   :jsonparam string body: JSON object containing gitprovider description
   :type name: string

   Create new gitprovider.

   **Example JSON body**

   .. sourcecode:: http

      {
          "type": "bitbucket",
          "auth": {
            "username": "my-username",
            "password": "password1234"
          }
      }

   **Example request**

   .. sourcecode:: http

      $ curl -XPUT '/global/gitproviders?name=mygitprovider' -d '{
          "type": "bitbucket",
          "auth": {
            "username": "my-username",
            "password": "password1234"
          }
      }'

.. http:patch::   /global/gitproviders/(string:gitprovider)

   :jsonparam string body: JSON object containing gitprovider fields to modify

   Modify gitprovider. Only fields provided in JSON body will be changed.

   .. NOTE::
      The only valid field to modify is "auth".

   **Example request**

   .. sourcecode:: http

      $ curl -XPATCH '/global/gitproviders/mygitprovider' -d '{ "auth": {
            "username": "my-username",
            "password": "password1234"
          }
       }'

.. http:delete::   /global/gitproviders/(string:gitprovider)

   Remove gitprovider.

   **Example request**

   .. sourcecode:: http

      $ curl -XGET '/global/gitproviders/mygitprovider'

Keypairs
--------

.. http:get::   /global/keypairs

   Get list of keypairs.

   **Example request**

   .. sourcecode:: http

      $ curl -XGET '/global/keypairs'


.. http:get::   /global/keypairs/(string:keypair)

   Get information about a keypair.

   **Example request**

   .. sourcecode:: http

      $ curl -XGET '/global/keypairs/mykeypair'


.. http:put::   /global/keypairs/(string:keypair)

   :param name: keypair name (URL-encoded)
   :param type: keypair type ("git" or "salt")
   :jsonparam string body: JSON object containing JSON-encoded public and private keys
   :type name: string
   :type type: string

   Create new keypair.

   **Example JSON body**

   .. NOTE::
      Key data omitted from examples for brevity.

   .. sourcecode:: http

      {
          "private_key": "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n",
          "public_key": "ssh-rsa ... foo@bar.com\\n"
      }

   **Example request**

   .. sourcecode:: http

      $ curl -XPUT '/global/keypairs?type=git&name=mykeypair' -d '{
          "private_key": "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n",
          "public_key": "ssh-rsa ... foo@bar.com\\n"
      }'

.. http:patch::   /global/keypairs/(string:keypair)

   :jsonparam string body: JSON object containing key(s) to modify

   Modify keypair by replacing keys. Only keys provided in JSON body will be changed,
   but you will almost always want to specify both.

   **Example request**

   .. sourcecode:: http

      $ curl -XPATCH '/global/keypairs/mykeypair' -d '{
          "private_key": "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----\\n",
          "public_key": "ssh-rsa ... foo@bar.com\\n"
       }'

.. http:delete::   /global/keypairs/(string:keypair)

   Remove keypair.

   **Example request**

   .. sourcecode:: http

      $ curl -XDELETE '/global/keypair/mykeypair'

