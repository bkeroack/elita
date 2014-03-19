================
Global Endpoints
================
(only supported verbs are shown for each endpoint)


=====
Users
=====

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


.. http:get::   /global/gitproviders

   Get list of gitproviders.

   **Example request**

   .. sourcecode:: http

      $ curl -XGET '/global/gitproviders'


.. http:get::   /global/gitproviders/(string:gitprovider)

   Get information about gitprovider.

   **Example request**

   .. sourcecode:: http

      $ curl -XGET '/global/gitproviders/mygitprovider'



======
Tokens
======