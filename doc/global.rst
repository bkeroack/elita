
============
Universal Parameters
============

The following parameters are available on all endpoints for all verbs:

    #.   pretty
        'pretty=true' (or 'True' or 'yes') for pretty-printed JSON response
    #.   auth_token
        Required for most endpoints (with a few exceptions, see below)


============
Global Endpoints
============
(only supported verbs are shown for each endpoint)



* /global

    *   GET
        Returns the available child endpoints

        Ex.::

            {
            "global": [
            "tokens",
            "users"
            ]
            }

* /global/users

    *   GET
        Returns terse list of users

        Ex.::

            {
                "users": [
                    "admin",
                    "robert",
                    "mary",
                    "john"
                ]
            }

    *   PUT/POST
        Creates a new user or modifies an existing user.

        Required URL parameters:
            *   username (string)
            *   password (string)

        Required body parameter:
            Must be a valid JSON document containing the following keys:
                * "permissions" - a valid permissions object
                * "attributes" - (optional) a free form JSON object for custom user attributes

    *   DELETE
        Deletes an existing user

        Required URL parameters:
            * username (string)