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

   .. sourcecode:: bash

      $ curl -XGET '/server'

   **Example response**

   .. sourcecode:: json

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

   .. sourcecode:: bash

      $ curl -XGET '/server/server0'

   **Example response**

   .. sourcecode:: json

      {
            "created_datetime": "2014-01-27 20:23:58+00:00",
            "environment": "production",
            "gitdeploys": [ "MainGD" ],
            "server_name": "server0",
            "attributes": {}
      }


Create Server
^^^^^^^^^^^^^

.. http:put::   /server

   :param name: server name (salt minion name)
   :type name: string
   :param environment: environment name
   :type environment: string
   :param existing: does server exist (currently unused)
   :type existing: boolean ("true"/"false")

   Create a server object.

   .. ATTENTION::
      Elita assumes that any server can be accessed via salt by name. For example, if you create a server object 'web01',
      you should be able to issue the following command successfully from the machine running Elita:
      .. sourcecode:: bash

         $ salt 'web01' test.ping

   **Example request**:

   .. sourcecode:: bash

      $ curl -XPUT '/server?name=web01&environment=production&existing=true'

Delete Server
^^^^^^^^^^^^^

.. http:delete::   /server/(string: server_name)

   Remove a server object. This does not remove the server from Salt.

   **Example request**:

   .. sourcecode:: bash

      $ curl -XDELETE '/server/web01'


Environments
------------

Environments are created using an attribute specified on the server object, used to logically group servers.

.. NOTE::
   Elita environments are entirely independent from Salt environments. They are calculated from the "environment"
   field on all available server objects.

View Available Environments
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. http:get::   /server/environments

   View a census of all available environments with a list of associated servers for each.


   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/server/environments'

   **Example response**

   .. sourcecode:: json

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

