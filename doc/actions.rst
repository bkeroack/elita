================
Action Endpoints
================
(only supported verbs are shown for each endpoint)

.. contents:: Contents

Actions are dynamically loaded endpoints from plugins.

Actions
-------

View Actions
^^^^^^^^^^^^

.. http:get::   /app/(string: application)/actions

   Returns list of available actions.


   **Example request**:

   .. sourcecode:: http

      $ curl -XGET '/app/widgetmaker/actions'

   **Example response**

   .. sourcecode:: http

      {
            "application": "widgetmaker",
            "actions": [
                "ExampleAction1",
                "SpecialDeploymentAction",
                "CleanupAction"
            ]
      }


View Action Detail
^^^^^^^^^^^^^^^^^^

.. http:get::   /app/(string: application)/actions/(string: action name)

   Returns information about a specific action, including required parameters.

   .. NOTE::
      Parameter types are not enforced. They exist for documentation purposes only.


   **Example request**:

   .. sourcecode:: http

      $ curl -XGET '/app/widgetmaker/actions/CleanupAction'

   **Example response**

   .. sourcecode:: http

      {
            "action": {
                "post_parameters": {
                    "days": {
                        "type": "integer",
                        "description": "clean builds older than this many days"
                    },
                    "delete": {
                        "type": "boolean (string)",
                        "description": "delete builds (true or false)"
                    }
                },
                "name": "CleanupAction"
            },
            "application": "widgetmaker"
      }


Execute Action
^^^^^^^^^^^^^^

.. http:post::   /app/(string: application)/actions/(string: action name)

   :param various: *various parameters* - specified via plugin, all parameters are required

   Execute a named action. All parameters must be supplied or an error response will be generated.

   **Example request**:

   .. sourcecode:: http

      $ curl -XPOST '/app/widgetmaker/actions/CleanupAction?delete=true&days=30'

   **Example response**

   .. sourcecode:: http

      {
            "status": "ok",
            "message": {
                "action": "CleanupAction",
                "status": "async/running",
                "job_id": "85982318-af22-4d5a-a8ce-725601ac24f4"
            }
      }
