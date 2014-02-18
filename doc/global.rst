
=================
Common Parameters
=================

The following parameters are available on all endpoints for all verbs:

    #.   pretty
        'pretty=true' (or 'True' or 'yes') for pretty-printed JSON response
    #.   auth_token
        Required for most endpoints (with a few exceptions, see below)

.. NOTE::
   For readability, hostname/port and auth_token parameter are excluded from all example API calls.

================
Case Sensitivity
================

daft URIs are case-sensitive. The following two endpoints are not equivalent:

.. sourcecode:: http

   /app/exampleapp/actions/ScriptedAction
   /app/exampleapp/actions/scriptedaction   #not the same

According to `RFC 4343 <http://tools.ietf.org/html/rfc4343>`_, domain names are not case sensitive. URIs *are*
considered case sensitive according to `W3C <http://www.w3.org/TR/WD-html40-970708/htmlweb.html>`_.

================
Global Endpoints
================
(only supported verbs are shown for each endpoint)



.. http:get::   /global/users

   Returns terse list of users


   **Example request**:

   .. sourcecode:: http

      $ curl -XGET '/global/users'

   **Example response**:

   .. sourcecode:: http

      {
          "users": [
              "admin",
              "robert",
              "mary",
              "john"
          ]
      }

.. http:post::  /global/users

   Creates a new user or modifies an existing user.

   :param username: Username (URL-encoded)
   :param password: Password (URL-encoded, optional with auth_token)
   :param auth_token: Auth token (optional if password provided)
   :type username: string
   :type password: string
   :type auth_token: string
   :jsonparam string body: JSON object containing permissions object and optional attributes object.

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

  This would grant the following permissions:

  * Give user read/write access to all applications EXCEPT newapp
  * Give execute permission to "ScriptedAction" only under newapp
  * Give execute permission to all actions under otherapp
  * Do not give any permissions to any servers

.. http:get::   /global/users/(string:username)

   Get a user and create and return an auth token (if necessary)

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

