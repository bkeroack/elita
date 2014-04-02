================
Server Endpoints
================
(only supported verbs are shown for each endpoint)

.. contents:: Contents

Server objects represent the physical servers to which you want to deploy code or apply actions.

.. ATTENTION::
   As of the current version, Elita does not do any provisioning (mainly because nobody has had time to implement it
   yet). Elita assumes that any server objects you create refer to machines accessible to the local salt installation
   (the name of the minion must match the name of the server object).

Servers
-------

View Servers
^^^^^^^^^^^^

.. http:get::   /server

   Returns list of available servers.


   **Example request**:

   .. sourcecode:: http

      $ curl -XGET '/server'

   **Example response**

   .. sourcecode:: http

      {
            "servers": [
                "server0",
                "server1"
            ]
      }


View Server Detail
^^^^^^^^^^^^^^^^^^

.. http:get::   /server/(string: server)

   Returns detailed information about a particular server, including a list of gitdeploys (see:
   :ref:`gitdeploy-explanation`).


   **Example request**:

   .. sourcecode:: http

      $ curl -XGET '/server/server0'

   **Example response**

   .. sourcecode:: http

      {
            "created_datetime": "2014-01-27 20:23:58+00:00",
            "environment": "production",
            "gitdeploys": [ "MainGD" ],
            "server_name": "server0",
            "attributes": {}
      }


Create Server
^^^^^^^^^^^^^

Modify Server
^^^^^^^^^^^^^

Environments
------------

Environments are created using an attribute specified on the server object, used to logically group servers.

View Available Environments
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. http:get::   /server/environments

   View a census of all available environments with a list of associated servers for each.


   **Example request**:

   .. sourcecode:: http

      $ curl -XGET '/server/environments'

   **Example response**

   .. sourcecode:: http

      {
            "environments": {
                "production": [
                    "server0",
                    "server1"
                ],
                "testing": [
                    "testing0",
                    "testing1"
                ]
            }
      }

