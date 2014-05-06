=========
Endpoints
=========

.. contents:: Contents

Top-Level Containers
--------------------

The following top-level containers are available:

* ``/app`` - Application container
* ``/global`` - Site-wide global objects (users, tokens, etc.)
* ``/job`` - Asynchronous jobs
* ``/server`` - Server objects

In general, Elita distinguishes between two primary resource types: containers and objects (some like
/app are both). You issue a PUT on a container to create an object (the object doesn't exist yet so
you can't do a PUT directly on it). You issue a PATCH on an object to change it, a DELETE to remove it or a POST to
trigger some action (such as the deployment or action objects). For legacy purposes,
most containers also support DELETE with URL parameters to specify removal of child objects (in other words,
the inverse of the PUT operation that created it).

Kind of a weird convention (for no particular reason other than consistency) is that all top-level containers are
singular ('app', 'global', 'job', etc.) but any sub-containers are plural ( '/app/builds',
etc.). There's no good reason but we're sticking with it.

Documentation:

.. toctree::

   urlmap.rst
   app.rst
   global.rst
   actions.rst
   job.rst
   server.rst


HTTP Verbs
----------

Elita supports the following HTTP Verbs:

* GET       -   Retrieve a resource.
* PUT       -   Create a resource.
* DELETE    -   Remove a resource.
* PATCH     -   Change a resource.
* POST      -   Trigger an action or procedure.


Common Parameters
-----------------

The following parameters are available on all endpoints for all verbs:

* ``auth_token``:  (URL parameter) Authorization token (required for all resources that don't accept a password URL parameter)

  -OR-

* ``Auth-Token``: (Header) Authorization token.

.. NOTE::
   Exactly one of auth_token or Auth-Token must be provided for every resource that requires authorization. Multiple auth_token
   parameters/headers are considered errors and will result in authentication failure.

* ``pretty``: Pretty-print JSON response? ("true", "false", "yes", "no")

.. ATTENTION::
   For readability, hostname/port and auth_token parameter are excluded from all example URIs and API calls.
   Nearly every resource requires some form of authentication (auth_token in the majority of cases or password)


Case Sensitivity
----------------

URIs are case-sensitive. The following two endpoints are not equivalent:

   ``/app/exampleapp/actions/ScriptedAction``

Contrasted with...

   ``/app/exampleapp/actions/scriptedaction``  Not the same!

.. NOTE::
   References:
   `W3C <http://www.w3.org/TR/WD-html40-970708/htmlweb.html>`_
   `RFC 4343 <http://tools.ietf.org/html/rfc4343>`_
